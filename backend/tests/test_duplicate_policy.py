"""API-level tests for the hardcoded same-day duplicate-run policy.

自测口径：合格样例连开两次 → 第二次必须被拒绝（409），且留痕可查；
接口报错文案与留痕记录是同一条（页面原样展示接口文案）。
"""

from datetime import datetime, timedelta, timezone

from app.models import Job
from app.policy import CUSTOM_TEXT_MAX_CHARS, EVENT_DUPLICATE_RUN_REJECTED
from tests.conftest import GOOD_FASTQ


def test_good_sample_twice_same_day_rejected_and_audited(
    client, db, bioops_headers, auditor_headers, good_sample
):
    first = client.post("/api/jobs", json={"sampleId": good_sample.id}, headers=bioops_headers)
    assert first.status_code == 201, first.text
    first_job_id = first.json()["id"]

    second = client.post("/api/jobs", json={"sampleId": good_sample.id}, headers=bioops_headers)
    assert second.status_code == 409, second.text
    detail = second.json()["detail"]
    assert "拒绝重复开跑" in detail
    assert good_sample.name in detail
    assert f"作业 #{first_job_id}" in detail
    assert "同一样例同日仅允许开跑一次" in detail

    # 留痕可追溯：审计员也能查到这次被拒绝的重复尝试，文案与接口一致
    events = client.get("/api/audit-events", headers=auditor_headers)
    assert events.status_code == 200
    rows = events.json()
    assert len(rows) == 1
    event = rows[0]
    assert event["event_type"] == EVENT_DUPLICATE_RUN_REJECTED
    assert event["username"] == "bioops"
    assert event["sample_id"] == good_sample.id
    assert event["job_id"] == first_job_id
    assert event["detail"] == detail


def test_previous_day_job_does_not_block(client, db, bioops_headers, good_sample):
    first = client.post("/api/jobs", json={"sampleId": good_sample.id}, headers=bioops_headers)
    assert first.status_code == 201, first.text

    job = db.query(Job).filter(Job.id == first.json()["id"]).first()
    job.created_at = datetime.now(timezone.utc) - timedelta(days=2)
    db.commit()

    second = client.post("/api/jobs", json={"sampleId": good_sample.id}, headers=bioops_headers)
    assert second.status_code == 201, second.text


def test_auditor_cannot_create_job(client, auditor_headers, good_sample):
    resp = client.post("/api/jobs", json={"sampleId": good_sample.id}, headers=auditor_headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "仅运维账号可提交质控作业"


def test_custom_text_rules(client, bioops_headers):
    # 空文本
    resp = client.post("/api/jobs", json={"fastqText": "   "}, headers=bioops_headers)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "请提供 sampleId 或 fastqText"

    # 首行不是 @ 开头
    resp = client.post("/api/jobs", json={"fastqText": "not-a-fastq"}, headers=bioops_headers)
    assert resp.status_code == 400
    assert "首行须以 @ 开头" in resp.json()["detail"]

    # 超长
    too_long = "@" + "A" * CUSTOM_TEXT_MAX_CHARS
    resp = client.post("/api/jobs", json={"fastqText": too_long}, headers=bioops_headers)
    assert resp.status_code == 400
    assert "过长" in resp.json()["detail"]

    # 合格文本：可提交；自定义文本不参与同日去重，连开两次均放行
    for _ in range(2):
        resp = client.post("/api/jobs", json={"fastqText": GOOD_FASTQ}, headers=bioops_headers)
        assert resp.status_code == 201, resp.text


def test_different_samples_do_not_block(client, db, bioops_headers, good_sample):
    from app.models import Sample

    other = Sample(
        name="demo-good-r2",
        description="另一个合格样例",
        is_broken=False,
        fastq_content=GOOD_FASTQ,
    )
    db.add(other)
    db.commit()

    for sample_id in (good_sample.id, other.id):
        resp = client.post("/api/jobs", json={"sampleId": sample_id}, headers=bioops_headers)
        assert resp.status_code == 201, resp.text
