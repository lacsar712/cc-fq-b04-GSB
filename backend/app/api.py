from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.auth import authenticate_user, create_access_token, get_current_user
from app.database import SessionLocal, get_db
from app.models import Job, JobAttempt, JobStage, Sample
from app.pipeline.runner import create_job_stages, run_pipeline_sync
from app.policy import (
    ACTION_CREATED,
    ACTION_REJECTED_DUPLICATE,
    ACTION_REJECTED_FORBIDDEN,
    MAX_FASTQ_TEXT_LEN,
    duplicate_message,
    fastq_content_hash,
    find_same_day_duplicate,
    normalize_fastq_text,
    record_attempt,
)
from app.schemas import (
    AttemptOut,
    HealthOut,
    JobCreate,
    JobListItem,
    JobOut,
    LoginRequest,
    SampleOut,
    StageOut,
    TokenResponse,
)


router = APIRouter(prefix="/api")


def _run_job_background(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            run_pipeline_sync(db, job)
    finally:
        db.close()


@router.get("/health", response_model=HealthOut)
def health():
    return HealthOut(status="ok", service="fastq-qc-pipeline")


@router.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest):
    user = authenticate_user(body.username.strip(), body.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token = create_access_token(user["username"], user["role"])
    return TokenResponse(
        access_token=token,
        username=user["username"],
        role=user["role"],
    )


@router.get("/samples", response_model=list[SampleOut])
def list_samples(_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Sample).order_by(Sample.id).all()


@router.post("/jobs", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def create_job(
    body: JobCreate,
    background: BackgroundTasks,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sample_id = body.sampleId
    fastq_text = normalize_fastq_text(body.fastqText) if body.fastqText else ""
    sample_name = "自定义输入"
    sample = None

    # 1) 角色校验（写死）：审计员只读，不可开跑；越权尝试留痕后返回 403
    if user["role"] != "bioops":
        audit_sample_name = ""
        if sample_id is not None:
            target = db.query(Sample).filter(Sample.id == sample_id).first()
            audit_sample_name = target.name if target else f"未知样例 #{sample_id}"
        elif fastq_text:
            audit_sample_name = "自定义输入"
        detail = "审计员为只读角色，不可开跑质控作业，本次尝试已记录。"
        record_attempt(
            db,
            username=user["username"],
            role=user["role"],
            action=ACTION_REJECTED_FORBIDDEN,
            sample_id=sample_id,
            sample_name=audit_sample_name,
            detail=detail,
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)

    # 2) 输入校验
    if sample_id is not None:
        sample = db.query(Sample).filter(Sample.id == sample_id).first()
        if not sample:
            raise HTTPException(status_code=404, detail="样例不存在")
        fastq_text = sample.fastq_content
        sample_name = sample.name
    elif not fastq_text:
        raise HTTPException(status_code=400, detail="请提供 sampleId 或 fastqText")
    elif len(fastq_text) > MAX_FASTQ_TEXT_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"自定义文本过长（{len(fastq_text)} 字符），上限 {MAX_FASTQ_TEXT_LEN} 字符",
        )

    # 3) 同日重复开跑校验（写死）：同一样例 / 同一文本当日只允许开跑一次
    content_hash = None if sample else fastq_content_hash(fastq_text)
    existing = find_same_day_duplicate(
        db, sample_id=sample.id if sample else None, content_hash=content_hash
    )
    if existing is not None:
        message = duplicate_message(existing)
        record_attempt(
            db,
            username=user["username"],
            role=user["role"],
            action=ACTION_REJECTED_DUPLICATE,
            sample_id=existing.sample_id,
            sample_name=existing.sample_name,
            content_hash=content_hash,
            job_id=existing.id,
            detail=message,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "duplicate_same_day",
                "message": message,
                "existingJobId": existing.id,
            },
        )

    job = Job(
        sample_id=sample.id if sample else None,
        sample_name=sample_name,
        status="pending",
        created_by=user["username"],
        fastq_snapshot=fastq_text,
        content_hash=content_hash,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    create_job_stages(db, job.id)
    record_attempt(
        db,
        username=user["username"],
        role=user["role"],
        action=ACTION_CREATED,
        sample_id=job.sample_id,
        sample_name=job.sample_name,
        content_hash=content_hash,
        job_id=job.id,
        detail=f"作业 #{job.id} 已创建并入队",
    )
    background.add_task(_run_job_background, job.id)

    job = (
        db.query(Job)
        .options(joinedload(Job.stages))
        .filter(Job.id == job.id)
        .first()
    )
    return job


@router.get("/attempts", response_model=list[AttemptOut])
def list_attempts(_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """开跑尝试审计列表（含被拒的重复/越权尝试），所有登录用户可查。"""
    return db.query(JobAttempt).order_by(JobAttempt.id.desc()).limit(200).all()


@router.get("/jobs", response_model=list[JobListItem])
def list_jobs(_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Job).order_by(Job.id.desc()).all()


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, _user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    job = (
        db.query(Job)
        .options(joinedload(Job.stages))
        .filter(Job.id == job_id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="作业不存在")
    return job


@router.get("/jobs/{job_id}/stages", response_model=list[StageOut])
def get_job_stages(
    job_id: int, _user: dict = Depends(get_current_user), db: Session = Depends(get_db)
):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="作业不存在")
    return (
        db.query(JobStage)
        .filter(JobStage.job_id == job_id)
        .order_by(JobStage.stage_order)
        .all()
    )
