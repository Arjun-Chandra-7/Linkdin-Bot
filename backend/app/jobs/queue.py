"""Durable job queue backed by the database.

Jobs live in SQLite, so a laptop restart (or sleep) never loses queued work.
Duplicate prevention is by unique ``idempotency_key``; failures retry with
exponential backoff up to ``max_attempts`` and then land in DEAD for
inspection rather than disappearing.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logging import log_event
from app.database.base import utcnow
from app.database.enums import JobStatus
from app.database.models import Job

log = logging.getLogger(__name__)

BACKOFF_BASE_SECONDS = 30
BACKOFF_MAX_SECONDS = 3600


def enqueue(
    db: Session,
    job_type: str,
    payload: dict[str, Any] | None = None,
    *,
    run_at=None,
    idempotency_key: str | None = None,
    max_attempts: int = 5,
) -> Job:
    """Queue a job. Re-enqueuing the same idempotency key returns the original."""
    if idempotency_key:
        existing = db.execute(
            select(Job).where(Job.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        if existing is not None:
            # Re-arm a job that already ran or died only if the caller moved
            # its schedule earlier; otherwise leave history intact.
            if existing.status in {JobStatus.SUCCEEDED, JobStatus.DEAD, JobStatus.CANCELLED}:
                return existing
            if run_at is not None and run_at < existing.run_at:
                existing.run_at = run_at
                db.flush()
            return existing

    job = Job(
        type=job_type,
        payload=payload or {},
        status=JobStatus.QUEUED,
        run_at=run_at or utcnow(),
        max_attempts=max_attempts,
        idempotency_key=idempotency_key,
    )
    db.add(job)
    try:
        db.flush()
    except IntegrityError:
        # Lost a race on the unique key: return the winner.
        db.rollback()
        return db.execute(
            select(Job).where(Job.idempotency_key == idempotency_key)
        ).scalar_one()
    log_event(log, "JOB_ENQUEUED", job_id=job.id, type=job_type, run_at=job.run_at.isoformat())
    return job


def claim_due_jobs(db: Session, worker_id: str, limit: int = 5) -> list[Job]:
    """Atomically take ownership of jobs that are due."""
    now = utcnow()
    due = (
        db.execute(
            select(Job)
            .where(Job.status == JobStatus.QUEUED, Job.run_at <= now)
            .order_by(Job.run_at)
            .limit(limit)
            .with_for_update(nowait=False)
        )
        .scalars()
        .all()
    )
    claimed: list[Job] = []
    for job in due:
        job.status = JobStatus.RUNNING
        job.locked_by = worker_id
        job.locked_at = now
        job.started_at = now
        job.attempts += 1
        claimed.append(job)
    if claimed:
        db.commit()
    return claimed


def complete_job(db: Session, job: Job, result: dict[str, Any] | None = None) -> None:
    job.status = JobStatus.SUCCEEDED
    job.finished_at = utcnow()
    job.result = result
    job.locked_by = None
    job.last_error = None
    db.commit()
    log_event(log, "JOB_SUCCEEDED", job_id=job.id, type=job.type)


def fail_job(db: Session, job: Job, error: str) -> None:
    """Retry with exponential backoff, or mark DEAD once attempts run out."""
    job.locked_by = None
    job.last_error = error[:2000]
    if job.attempts >= job.max_attempts:
        job.status = JobStatus.DEAD
        job.finished_at = utcnow()
        log_event(log, "JOB_DEAD", level=logging.ERROR, job_id=job.id, type=job.type, error=error[:200])
    else:
        delay = min(BACKOFF_BASE_SECONDS * (2 ** (job.attempts - 1)), BACKOFF_MAX_SECONDS)
        job.status = JobStatus.QUEUED
        job.run_at = utcnow() + timedelta(seconds=delay)
        log_event(
            log,
            "JOB_RETRY_SCHEDULED",
            level=logging.WARNING,
            job_id=job.id,
            type=job.type,
            attempt=job.attempts,
            retry_in_seconds=delay,
        )
    db.commit()


def recover_orphaned_jobs(db: Session) -> int:
    """Requeue jobs left RUNNING by a crash or an abrupt shutdown."""
    orphans = db.execute(select(Job).where(Job.status == JobStatus.RUNNING)).scalars().all()
    for job in orphans:
        job.status = JobStatus.QUEUED
        job.locked_by = None
        job.run_at = utcnow()
    if orphans:
        db.commit()
        log_event(log, "JOBS_RECOVERED", count=len(orphans))
    return len(orphans)
