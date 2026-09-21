"""同日重复开跑的写死策略与开跑尝试审计。

策略（写死，不接受请求参数覆盖）：
- 同一自然日（UTC 日期）内，同一样例只允许开跑一次，第二次直接拒绝（HTTP 409）。
- 样例库提交按 sample_id 判重；纯文本自定义输入按规范化文本的 SHA-256 判重，
  两个池子互相独立（自定义文本规则见 README「纯文本自定义输入规则」）。
- 无论上一次作业成功 / 失败 / 排队中，都计入判重。
- 每一次开跑尝试（成功、重复被拒、越权被拒）都写入 job_attempts 表，供追溯。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Job, JobAttempt

# 纯文本自定义输入的最大长度（字符数），超出直接 400
MAX_FASTQ_TEXT_LEN = 200_000

ACTION_CREATED = "created"
ACTION_REJECTED_DUPLICATE = "rejected_duplicate"
ACTION_REJECTED_FORBIDDEN = "rejected_forbidden"


def normalize_fastq_text(text: str) -> str:
    """自定义文本规范化：统一换行为 LF，去掉首尾空白。"""
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def fastq_content_hash(normalized_text: str) -> str:
    """对规范化后的文本取 SHA-256，作为自定义输入的判重指纹。"""
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def _as_utc_date(dt: datetime) -> datetime.date:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date()


def find_same_day_duplicate(
    db: Session,
    *,
    sample_id: int | None = None,
    content_hash: str | None = None,
) -> Job | None:
    """返回当日（UTC）同源的最近一次作业；没有则返回 None。

    样例库提交按 sample_id 判重；自定义文本提交按 content_hash 判重
    （只在自定义文本作业池内比较，即 sample_id IS NULL）。
    """
    q = db.query(Job).order_by(Job.id.desc())
    if sample_id is not None:
        q = q.filter(Job.sample_id == sample_id)
    else:
        q = q.filter(Job.sample_id.is_(None), Job.content_hash == content_hash)

    today = datetime.now(timezone.utc).date()
    for job in q.limit(100).all():
        if job.created_at is not None and _as_utc_date(job.created_at) == today:
            return job
    return None


def duplicate_message(existing: Job) -> str:
    """拒绝文案：接口与前端页面共用同一句（前端原样展示接口返回的 message）。"""
    today = datetime.now(timezone.utc).date().isoformat()
    return (
        f"今日（UTC {today}）已对样例「{existing.sample_name}」开跑过质控"
        f"（作业 #{existing.id}，提交人 {existing.created_by}），"
        f"按写死策略同日不可重复开跑，本次已被拒绝并记录。"
    )


def record_attempt(
    db: Session,
    *,
    username: str,
    role: str,
    action: str,
    sample_id: int | None = None,
    sample_name: str = "",
    content_hash: str | None = None,
    job_id: int | None = None,
    detail: str = "",
) -> JobAttempt:
    attempt = JobAttempt(
        username=username,
        role=role,
        action=action,
        sample_id=sample_id,
        sample_name=sample_name,
        content_hash=content_hash,
        job_id=job_id,
        detail=detail,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt
