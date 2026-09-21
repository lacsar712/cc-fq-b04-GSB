"""Shared fixtures: run the full API against a throwaway SQLite file.

DATABASE_URL must be set before any app.* import, because app.database
creates the engine at import time. check_same_thread=false lets the
TestClient portal thread and the test thread share the pool.
"""

import os
import tempfile

_DB_DIR = tempfile.mkdtemp(prefix="fastq-qc-test-")
_DB_PATH = os.path.join(_DB_DIR, "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}?check_same_thread=false&timeout=30"
os.environ["JWT_SECRET"] = "test-secret"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.auth import create_access_token  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AuditEvent, Job, JobStage, Sample  # noqa: E402

GOOD_FASTQ = """@SEQ1
ACGTACGT
+
IIIIHHHH
@SEQ2
NNNNACGT
+
IIIIIIII
"""


@pytest.fixture()
def db():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    for model in (JobStage, AuditEvent, Job, Sample):
        session.query(model).delete()
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def bioops_headers():
    token = create_access_token("bioops", "bioops")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def auditor_headers():
    token = create_access_token("auditor", "auditor")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def good_sample(db):
    sample = Sample(
        name="demo-good-r1",
        description="合格小型 FASTQ 样例",
        is_broken=False,
        fastq_content=GOOD_FASTQ,
    )
    db.add(sample)
    db.commit()
    db.refresh(sample)
    return sample
