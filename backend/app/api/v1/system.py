"""Observability and the home dashboard.

Everything here reports real state. Where a component is not set up it says
``not_configured`` rather than inventing a green light.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.schemas import ComponentStatus, HomeSummary, SystemStatus
from app.config import get_settings
from app.core.settings_store import get_setting
from app.database.base import utcnow
from app.database.enums import (
    ConnectionStatus,
    DraftStatus,
    JobStatus,
    ScheduleStatus,
)
from app.database.models import (
    ConnectionCandidate,
    Device,
    Draft,
    Job,
    PublishedPost,
    ScheduledPost,
)
from app.database.session import get_db
from app.linkedin.publisher import PublisherStatus, get_publisher
from app.llm.factory import get_provider
from app.security.auth import get_current_device

router = APIRouter(prefix="/system", tags=["system"])

REVIEW_STATUSES = [DraftStatus.READY_FOR_REVIEW, DraftStatus.SAVED_FOR_LATER]
LINKEDIN_TOKEN_LIFETIME = timedelta(days=60)
LINKEDIN_TOKEN_WARNING = timedelta(days=7)


def _spoken_when(db: Session, when) -> str:
    from app.scheduler.service import get_timezone

    local = when.astimezone(get_timezone(db))
    today = utcnow().astimezone(get_timezone(db)).date()
    delta = (local.date() - today).days
    clock = local.strftime("%-I:%M %p").lower()
    if delta == 0:
        return f"today at {clock}"
    if delta == 1:
        return f"tomorrow at {clock}"
    return f"{local.strftime('%a %-d %b')} at {clock}"


def _count(db: Session, model, *conditions) -> int:
    stmt = select(func.count()).select_from(model)
    if conditions:
        stmt = stmt.where(*conditions)
    return int(db.execute(stmt).scalar_one())


def _linkedin_status(publisher_status: PublisherStatus, token_issued_at: str) -> ComponentStatus:
    status = ComponentStatus(
        name="linkedin", status=publisher_status.status, detail=publisher_status.detail
    )
    if publisher_status.status != "ok" or not token_issued_at:
        return status

    try:
        issued_at = datetime.fromisoformat(token_issued_at.replace("Z", "+00:00"))
        if issued_at.tzinfo is None:
            issued_at = issued_at.replace(tzinfo=UTC)
    except ValueError:
        return ComponentStatus(
            name="linkedin",
            status="degraded",
            detail="LinkedIn token issue date is invalid. Reconnect LinkedIn to refresh it.",
        )

    expires_at = issued_at.astimezone(UTC) + LINKEDIN_TOKEN_LIFETIME
    if expires_at - utcnow() <= LINKEDIN_TOKEN_WARNING:
        return ComponentStatus(
            name="linkedin",
            status="degraded",
            detail=(
                f"LinkedIn access token expires around {expires_at.date().isoformat()}. "
                "Reconnect LinkedIn now to avoid interrupted publishing."
            ),
        )
    return status


@router.get("/status", response_model=SystemStatus)
def system_status(
    db: Session = Depends(get_db), _: Device = Depends(get_current_device)
) -> SystemStatus:
    settings = get_settings()

    try:
        db.execute(select(1))
        database = ComponentStatus(
            name="database", status="ok", detail=settings.database_url.split("/")[-1]
        )
    except Exception as exc:  # pragma: no cover
        database = ComponentStatus(name="database", status="error", detail=str(exc)[:200])

    provider_status = get_provider().health_check()
    ai = ComponentStatus(
        name="ai_provider", status=provider_status.status, detail=provider_status.detail
    )

    publisher_status = get_publisher(settings).health_check()
    linkedin = _linkedin_status(publisher_status, settings.linkedin_token_issued_at)

    next_job = (
        db.execute(select(Job).where(Job.status == JobStatus.QUEUED).order_by(Job.run_at).limit(1))
        .scalars()
        .first()
    )
    failed_jobs = _count(db, Job, Job.status.in_([JobStatus.DEAD, JobStatus.FAILED]))

    last_discovery = db.execute(
        select(func.max(Job.finished_at)).where(
            Job.type == "discover_topics", Job.status == JobStatus.SUCCEEDED
        )
    ).scalar_one_or_none()

    scheduler = ComponentStatus(
        name="scheduler",
        status="ok" if settings.scheduler_enabled else "disabled",
        # Shown to a person, so say it the way a person would.
        detail=(f"Next job {_spoken_when(db, next_job.run_at)}" if next_job else "No jobs queued."),
    )

    return SystemStatus(
        backend=ComponentStatus(name="backend", status="ok", detail=f"env={settings.app_env}"),
        database=database,
        scheduler=scheduler,
        ai_provider=ai,
        linkedin=linkedin,
        last_discovery_at=last_discovery,
        next_scheduled_job_at=next_job.run_at if next_job else None,
        failed_jobs=failed_jobs,
        server_time=utcnow(),
        timezone=get_setting(db, "timezone"),
    )


@router.get("/home", response_model=HomeSummary)
def home(db: Session = Depends(get_db), _: Device = Depends(get_current_device)) -> HomeSummary:
    week_ago = utcnow() - timedelta(days=7)

    next_slot = (
        db.execute(
            select(ScheduledPost)
            .where(ScheduledPost.status == ScheduleStatus.PENDING)
            .order_by(ScheduledPost.scheduled_at)
            .limit(1)
        )
        .scalars()
        .first()
    )
    next_title = None
    if next_slot is not None:
        draft = db.get(Draft, next_slot.draft_id)
        next_title = draft.title if draft else None

    # "Best format" is only stated once there is enough published history to
    # mean anything; otherwise the app shows an empty state.
    best_format = None
    published_count = _count(db, PublishedPost)
    if published_count >= 4:
        row = db.execute(
            select(PublishedPost.post_type, func.count())
            .group_by(PublishedPost.post_type)
            .order_by(func.count().desc())
            .limit(1)
        ).first()
        best_format = row[0] if row else None

    return HomeSummary(
        pending_approvals=_count(db, Draft, Draft.status.in_(REVIEW_STATUSES)),
        scheduled_posts=_count(db, ScheduledPost, ScheduledPost.status == ScheduleStatus.PENDING),
        published_this_week=_count(db, PublishedPost, PublishedPost.published_at >= week_ago),
        suggested_connections=_count(
            db, ConnectionCandidate, ConnectionCandidate.status == ConnectionStatus.NEW
        ),
        next_scheduled_at=next_slot.scheduled_at if next_slot else None,
        next_scheduled_title=next_title,
        best_recent_format=best_format,
        backend_status="connected",
    )


@router.post("/run/{job_type}")
def run_job_now(
    job_type: str,
    db: Session = Depends(get_db),
    _: Device = Depends(get_current_device),
) -> dict:
    """Trigger a pipeline job on demand (discovery, learning report).

    Only whitelisted, side-effect-safe job types are exposed; publishing is
    never triggerable this way because it must go through the scheduler and
    the approval gate.
    """
    from app.core.errors import ValidationError
    from app.jobs.queue import enqueue

    allowed = {"discover_topics", "generate_learning_report", "daily_loop"}
    if job_type not in allowed:
        raise ValidationError(
            f"'{job_type}' cannot be triggered manually.",
            details={"allowed": sorted(allowed)},
        )
    job = enqueue(db, job_type, {}, idempotency_key=f"manual:{job_type}:{utcnow().isoformat()}")
    db.commit()
    return {"job_id": job.id, "type": job_type, "status": str(job.status)}


@router.get("/costs")
def costs(db: Session = Depends(get_db), _: Device = Depends(get_current_device)) -> dict:
    """Actual AI spend against the configured limits."""
    from app.llm.budget import current_spend

    spend = current_spend(db)
    return {
        "spent_last_24h_usd": round(spend["day"], 4),
        "spent_last_30d_usd": round(spend["month"], 4),
        "daily_limit_usd": float(get_setting(db, "llm_daily_cost_limit_usd")),
        "monthly_limit_usd": float(get_setting(db, "llm_monthly_cost_limit_usd")),
    }
