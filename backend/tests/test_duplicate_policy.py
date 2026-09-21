"""API 级测试：同日重复开跑写死策略 + 开跑尝试审计。

用 SQLite（StaticPool 共享内存连接）替代 Postgres，不依赖外部服务；
后台流水线通过替换 app.api.SessionLocal 真实跑一遍。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token
from app.database import Base, get_db
from app.main import app
from app.models import JobAttempt, Sample


GOOD_FASTQ = """@SEQ1
ACGTACGT
+
IIIIHHHH
@SEQ2
NNNNACGT
+
IIIIIIII
"""

OTHER_FASTQ = """@SEQ3
ACGTACGT
+
HHHHHHHH
"""


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # 后台任务也用测试库，流水线真实执行
    monkeypatch.setattr("app.api.SessionLocal", TestingSession)

    # 注意：不用 with TestClient(app)，避免触发 lifespan 去连 Postgres
    c = TestClient(app)
    c.testing_session = TestingSession
    yield c

    app.dependency_overrides.clear()


def auth_headers(username: str, role: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(username, role)}"}


@pytest.fixture()
def bioops():
    return auth_headers("bioops", "bioops")


@pytest.fixture()
def auditor():
    return auth_headers("auditor", "auditor")


def seed_sample(client, name="demo-good-r1", content=GOOD_FASTQ) -> int:
    db = client.testing_session()
    try:
        s = Sample(name=name, description="测试样例", is_broken=False, fastq_content=content)
        db.add(s)
        db.commit()
        db.refresh(s)
        return s.id
    finally:
        db.close()


def attempts(client):
    db = client.testing_session()
    try:
        return db.query(JobAttempt).order_by(JobAttempt.id).all()
    finally:
        db.close()


def test_same_day_second_run_rejected_for_sample(client, bioops):
    sid = seed_sample(client)

    r1 = client.post("/api/jobs", json={"sampleId": sid}, headers=bioops)
    assert r1.status_code == 201, r1.text
    job_id = r1.json()["id"]

    # 合格样例连开第二次 → 拒绝（写死策略）
    r2 = client.post("/api/jobs", json={"sampleId": sid}, headers=bioops)
    assert r2.status_code == 409, r2.text
    detail = r2.json()["detail"]
    assert detail["code"] == "duplicate_same_day"
    assert detail["existingJobId"] == job_id
    assert "同日不可重复开跑" in detail["message"]
    assert "demo-good-r1" in detail["message"]

    # 可追溯：一条 created + 一条 rejected_duplicate，均指向对应作业
    rows = attempts(client)
    assert [a.action for a in rows] == ["created", "rejected_duplicate"]
    assert rows[0].job_id == job_id
    assert rows[1].job_id == job_id
    assert rows[1].sample_name == "demo-good-r1"
    assert rows[1].detail == detail["message"]  # 留痕文案与接口文案一致


def test_same_day_second_run_rejected_for_custom_text(client, bioops):
    r1 = client.post("/api/jobs", json={"fastqText": GOOD_FASTQ}, headers=bioops)
    assert r1.status_code == 201, r1.text

    r2 = client.post("/api/jobs", json={"fastqText": GOOD_FASTQ}, headers=bioops)
    assert r2.status_code == 409, r2.text
    assert r2.json()["detail"]["code"] == "duplicate_same_day"


def test_normalized_text_still_counts_as_duplicate(client, bioops):
    r1 = client.post("/api/jobs", json={"fastqText": GOOD_FASTQ}, headers=bioops)
    assert r1.status_code == 201, r1.text

    # CRLF 换行 + 首尾空白：规范化后是同一段文本，仍判重
    variant = "\r\n  " + GOOD_FASTQ.replace("\n", "\r\n") + "\r\n\r\n"
    r2 = client.post("/api/jobs", json={"fastqText": variant}, headers=bioops)
    assert r2.status_code == 409, r2.text


def test_different_text_or_sample_allowed_same_day(client, bioops):
    sid = seed_sample(client)
    sid2 = seed_sample(client, name="demo-good-r2", content=OTHER_FASTQ)

    assert client.post("/api/jobs", json={"fastqText": GOOD_FASTQ}, headers=bioops).status_code == 201
    # 不同文本 → 允许
    assert client.post("/api/jobs", json={"fastqText": OTHER_FASTQ}, headers=bioops).status_code == 201
    # 不同样例 → 允许
    assert client.post("/api/jobs", json={"sampleId": sid}, headers=bioops).status_code == 201
    assert client.post("/api/jobs", json={"sampleId": sid2}, headers=bioops).status_code == 201


def test_auditor_cannot_submit_and_attempt_is_traced(client, auditor):
    sid = seed_sample(client)

    r = client.post("/api/jobs", json={"sampleId": sid}, headers=auditor)
    assert r.status_code == 403, r.text
    assert "只读" in r.json()["detail"]

    rows = attempts(client)
    assert len(rows) == 1
    assert rows[0].action == "rejected_forbidden"
    assert rows[0].username == "auditor"
    assert rows[0].sample_name == "demo-good-r1"


def test_attempts_endpoint_traceable_by_any_login(client, bioops, auditor):
    sid = seed_sample(client)
    client.post("/api/jobs", json={"sampleId": sid}, headers=bioops)
    client.post("/api/jobs", json={"sampleId": sid}, headers=bioops)  # 409
    client.post("/api/jobs", json={"sampleId": sid}, headers=auditor)  # 403

    # 审计员（只读）也能查看尝试记录
    r = client.get("/api/attempts", headers=auditor)
    assert r.status_code == 200, r.text
    actions = [a["action"] for a in r.json()]
    assert sorted(actions) == sorted(["created", "rejected_duplicate", "rejected_forbidden"])

    # 未登录不可查
    assert client.get("/api/attempts").status_code == 401


def test_empty_and_too_long_text_rejected(client, bioops):
    assert client.post("/api/jobs", json={}, headers=bioops).status_code == 400
    assert client.post("/api/jobs", json={"fastqText": "   \n "}, headers=bioops).status_code == 400

    too_long = "@A\n" + "A" * 200_000 + "\n+\n" + "I" * 200_000 + "\n"
    r = client.post("/api/jobs", json={"fastqText": too_long}, headers=bioops)
    assert r.status_code == 400
    assert "上限" in r.json()["detail"]


def test_first_run_pipeline_still_works(client, bioops):
    """策略不影响正常开跑：首次提交后流水线真实执行并产出指标。"""
    r = client.post("/api/jobs", json={"fastqText": GOOD_FASTQ}, headers=bioops)
    assert r.status_code == 201, r.text
    job = client.get(f"/api/jobs/{r.json()['id']}", headers=bioops).json()
    assert job["status"] == "success"
    assert job["metrics"]["reads"] == 2
    assert job["metrics"]["n_rate"] == 0.25
