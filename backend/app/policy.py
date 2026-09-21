"""写死策略：同一样例同日仅允许开跑一次（重复一律拒绝并留痕）。

本模块是策略的唯一出处：接口报错与页面提示共用同一条文案，
拒绝事件写入 audit_events 表以便追溯。

规则要点（与 README「同日同样例开跑策略」一节保持一致）：
- 粒度：按 sample_id，同一 UTC 自然日内已存在作业（任意状态、任意提交人）即拒绝。
- 自定义纯文本输入没有样例身份，不参与该去重，其规则见 validate_custom_fastq。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import AuditEvent, Job

# 写死：重复开跑的处理方式固定为「拒绝」（HTTP 409），不存在静默放行。
DUPLICATE_POLICY = "reject"

EVENT_DUPLICATE_RUN_REJECTED = "duplicate_run_rejected"

# 自定义纯文本输入规则（写死，README「自定义输入（纯文本）规则」一节逐条对应）
CUSTOM_TEXT_MAX_CHARS = 100_000


def utc_day_bounds(now: datetime) -> tuple[datetime, datetime]:
    """Return [start, end) of the UTC calendar day containing ``now``."""
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def find_same_day_job(db: Session, sample_id: int, now: datetime | None = None) -> Job | None:
    """Find an existing job for the sample created on the same UTC day (any status)."""
    now = now or datetime.now(timezone.utc)
    start, end = utc_day_bounds(now)
    return (
        db.query(Job)
        .filter(
            Job.sample_id == sample_id,
            Job.created_at >= start,
            Job.created_at < end,
        )
        .order_by(Job.id)
        .first()
    )


def duplicate_reject_message(sample_name: str, existing: Job, now: datetime | None = None) -> str:
    """The single canonical wording — API detail、页面横幅、留痕记录都用它。"""
    now = now or datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    return (
        f"拒绝重复开跑：样例「{sample_name}」今日（{day}，UTC）已开跑过"
        f"（作业 #{existing.id}，提交人 {existing.created_by}）。"
        f"写死策略：同一样例同日仅允许开跑一次，本次已拒绝并留痕。"
    )


def record_audit_event(
    db: Session,
    *,
    event_type: str,
    username: str,
    sample_id: int | None,
    sample_name: str,
    job_id: int | None,
    detail: str,
) -> AuditEvent:
    """Persist a traceable audit event (committed with the surrounding request)."""
    event = AuditEvent(
        event_type=event_type,
        username=username,
        sample_id=sample_id,
        sample_name=sample_name,
        job_id=job_id,
        detail=detail,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def validate_custom_fastq(text: str) -> str | None:
    """Validate plain-text custom FASTQ input. Returns error message or None.

    规则（写死）：
    1. 去首尾空白后不能为空；
    2. 长度不超过 CUSTOM_TEXT_MAX_CHARS 字符；
    3. 首行须以 @ 开头（FASTQ 表头）。
    更深的格式校验（四行一组、序列与质量串等长等）由 ParseActor 在流水线内完成，
    不合规时作业失败，而不是提交时被拒绝。
    """
    if not text:
        return "请提供 sampleId 或 fastqText"
    if len(text) > CUSTOM_TEXT_MAX_CHARS:
        return f"自定义 FASTQ 文本过长：最多 {CUSTOM_TEXT_MAX_CHARS} 字符（当前 {len(text)}）"
    first_line = text.split("\n", 1)[0]
    if not first_line.startswith("@"):
        return "自定义 FASTQ 文本首行须以 @ 开头（FASTQ 表头）"
    return None
