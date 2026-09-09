"""Job handlers.

Importing this module registers every handler with the registry.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.approvals.service import assert_publishable
from app.approvals.state_machine import assert_transition
from app.config import get_settings
from app.content.text import classify_hook
from app.core.errors import DomainError
from app.core.logging import log_event
from app.core.settings_store import get_setting
from app.database.base import utcnow
from app.database.enums import (
    DraftStatus,
    NotificationPriority,
    NotificationType,
    PublishMethod,
    ScheduleStatus,
)
from sqlalchemy import select

from app.database.models import (
    AnalyticsSnapshot,
    Draft,
    PublishedPost,
    ScheduledPost,
)
from app.jobs.registry import job_handler
from app.linkedin.publisher import get_publisher
from app.notifications.service import notify
from app.scheduler.service import get_timezone

log = logging.getLogger(__name__)


@job_handler("publish_post")
def publish_post(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Publish (or prepare for manual publication) one scheduled post.

    Every safety check lives here, because this is the only path to PUBLISHED:
    the slot must still be pending, and the draft must carry a valid approval
    whose hash matches the exact bytes about to go out.
    """
    slot_id = payload["scheduled_post_id"]
    slot = db.get(ScheduledPost, slot_id)
    if slot is None:
        return {"skipped": "scheduled post no longer exists"}

    # Idempotency: a re-delivered job must not publish a second time.
    if slot.status in {ScheduleStatus.PUBLISHED, ScheduleStatus.CANCELLED}:
        return {"skipped": f"slot already {slot.status}"}

    draft = db.get(Draft, slot.draft_id)
    if draft is None:
        return {"skipped": "draft no longer exists"}
    if draft.status == DraftStatus.PUBLISHED:
        return {"skipped": "draft already published"}

    try:
        approval, version = assert_publishable(db, draft)
    except DomainError as exc:
        slot.status = ScheduleStatus.CANCELLED
        slot.last_error = exc.message
        draft.failure_reason = exc.message
        db.flush()
        notify(
            db,
            type=NotificationType.PUBLISH_FAILED,
            title="Publishing blocked",
            body=exc.message,
            priority=NotificationPriority.HIGH,
            payload={"draft_id": draft.id, "code": exc.code, "recovery": exc.recovery},
            dedupe_key=f"publish-blocked:{slot.id}",
        )
        log_event(
            log, "PUBLISH_BLOCKED", level=logging.WARNING, draft_id=draft.id, reason=exc.code
        )
        return {"blocked": exc.code}

    slot.status = ScheduleStatus.PUBLISHING
    slot.attempts += 1
    assert_transition(DraftStatus(draft.status), DraftStatus.PUBLISHING)
    draft.status = DraftStatus.PUBLISHING
    db.flush()

    publisher = get_publisher(get_settings())
    try:
        result = publisher.publish(version.content, draft_id=draft.id)
    except DomainError as exc:
        slot.status = ScheduleStatus.FAILED
        slot.last_error = exc.message
        draft.status = DraftStatus.FAILED
        draft.failure_reason = exc.message
        db.flush()
        notify(
            db,
            type=NotificationType.PUBLISH_FAILED,
            title="Publishing failed",
            body=exc.message,
            priority=NotificationPriority.HIGH,
            payload={"draft_id": draft.id, "code": exc.code, "recovery": exc.recovery},
        )
        log_event(log, "PUBLISH_FAILED", level=logging.ERROR, draft_id=draft.id, reason=exc.code)
        return {"failed": exc.code}

    if not result.published and result.awaiting_user_action:
        # Manual mode: hand the user copy-ready text; they confirm afterwards.
        notify(
            db,
            type=NotificationType.PUBLISH_REMINDER,
            title="Time to post",
            body=f"{draft.title} is approved and ready to publish.",
            priority=NotificationPriority.HIGH,
            payload={
                "draft_id": draft.id,
                "scheduled_post_id": slot.id,
                "open_url": result.open_url,
                "action": "confirm_published",
            },
            dedupe_key=f"publish-reminder:{slot.id}",
        )
        log_event(log, "PUBLISH_REMINDER_SENT", draft_id=draft.id, slot_id=slot.id)
        return {"awaiting_user_action": True}

    record_publication(
        db,
        draft=draft,
        slot=slot,
        version=version,
        approval_id=approval.id,
        method=result.method,
        external_id=result.external_id,
        external_url=result.external_url,
    )
    return {"published": True, "external_id": result.external_id}


def record_publication(
    db: Session,
    *,
    draft: Draft,
    slot: ScheduledPost,
    version,
    approval_id: int,
    method: PublishMethod,
    external_id: str | None = None,
    external_url: str | None = None,
) -> PublishedPost:
    """Write the immutable published record and schedule analytics collection."""
    now = utcnow()
    local = now.astimezone(get_timezone(db))

    published = PublishedPost(
        draft_id=draft.id,
        version_id=version.id,
        approval_id=approval_id,
        content=version.content,
        content_hash=version.content_hash,
        published_at=now,
        method=method,
        external_id=external_id,
        external_url=external_url,
        post_type=draft.post_type,
        category=draft.category,
        char_count=version.char_count,
        hook_type=classify_hook(version.content),
        weekday=local.weekday(),
        hour_local=local.hour,
    )
    db.add(published)

    slot.status = ScheduleStatus.PUBLISHED
    assert_transition(DraftStatus(draft.status), DraftStatus.PUBLISHED)
    draft.status = DraftStatus.PUBLISHED
    db.flush()

    from app.jobs.queue import enqueue

    # First metrics sweep once the post has had time to gather any.
    from datetime import timedelta

    enqueue(
        db,
        "collect_analytics",
        {"published_post_id": published.id},
        run_at=now + timedelta(hours=float(get_setting(db, "analytics_interval_hours"))),
        idempotency_key=f"analytics:{published.id}:first",
    )

    log_event(
        log,
        "POST_PUBLISHED",
        draft_id=draft.id,
        published_post_id=published.id,
        method=str(method),
        external_id=external_id,
    )
    return published


# --------------------------------------------------------------------------
# The daily autonomous loop
# --------------------------------------------------------------------------


@job_handler("discover_topics")
def discover_topics(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Poll enabled sources, score candidates, and queue research on the best.

    Cost discipline lives here: everything is scored for free first, weak ideas
    are discarded, and only the top few ever reach a model.
    """
    from sqlalchemy import select

    from app.agents.discovery.idea_engine import ingest_items, reject_weak, select_promising
    from app.agents.discovery.sources import fetch_source
    from app.core.settings_store import get_setting
    from app.database.models import Source
    from app.jobs.queue import enqueue

    sources = db.execute(select(Source).where(Source.enabled.is_(True))).scalars().all()
    mix = get_setting(db, "category_mix") or {}
    ingested = 0
    errors: list[str] = []

    for source in sources:
        try:
            items = fetch_source(source)
        except Exception as exc:  # noqa: BLE001 - one bad feed must not stop the run
            source.last_error = f"{type(exc).__name__}: {exc}"[:500]
            errors.append(f"{source.name}: {type(exc).__name__}")
            log_event(log, "SOURCE_FETCH_FAILED", level=logging.WARNING, source_id=source.id)
            continue
        source.last_error = None
        source.last_fetched_at = utcnow()
        ingested += len(ingest_items(db, items, source_id=source.id, category_weights=mix))

    threshold = float(get_setting(db, "idea_score_threshold"))
    promising = select_promising(
        db, threshold=threshold, limit=int(get_setting(db, "max_research_per_run"))
    )
    rejected = reject_weak(db, threshold=threshold)

    for idea in promising:
        enqueue(db, "research_topic", {"idea_id": idea.id}, idempotency_key=f"research:{idea.id}")

    log_event(
        log,
        "DISCOVERY_COMPLETED",
        sources=len(sources),
        ingested=ingested,
        promising=len(promising),
        rejected=rejected,
    )
    return {
        "sources": len(sources),
        "ingested": ingested,
        "promising": len(promising),
        "rejected_weak": rejected,
        "errors": errors,
    }


@job_handler("research_topic")
def research_topic(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from app.agents.research.agent import research_idea
    from app.database.enums import IdeaStatus
    from app.database.models import Idea
    from app.jobs.queue import enqueue

    idea = db.get(Idea, payload["idea_id"])
    if idea is None:
        return {"skipped": "idea no longer exists"}
    if idea.status in {IdeaStatus.DRAFTED, IdeaStatus.ARCHIVED, IdeaStatus.REJECTED}:
        return {"skipped": f"idea already {idea.status}"}

    research = research_idea(db, idea)
    idea.status = IdeaStatus.RESEARCHED
    db.flush()

    enqueue(db, "generate_draft", {"idea_id": idea.id}, idempotency_key=f"draft:{idea.id}")
    return {"idea_id": idea.id, "claims": len(research.claims)}


@job_handler("generate_draft")
def generate_draft(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from app.agents.fact_checker.agent import check_draft, confidence_from_report
    from app.agents.writer.agent import generate_drafts
    from app.database.models import Idea, Research

    idea = db.get(Idea, payload["idea_id"])
    if idea is None:
        return {"skipped": "idea no longer exists"}

    outcome = generate_drafts(db, idea)
    if outcome.draft is None:
        return {"skipped": "no draft produced"}

    # Fact-check the chosen version and attach the report to it.
    if outcome.accepted and outcome.draft.current_version is not None:
        from sqlalchemy import select

        research = db.execute(
            select(Research).where(Research.idea_id == idea.id).order_by(Research.id.desc())
        ).scalars().first()
        report = check_draft(db, outcome.draft.current_version.content, research)
        outcome.draft.current_version.fact_check = report
        if report.get("unsupported_claims"):
            quality = dict(outcome.draft.current_version.quality or {})
            quality["claim_confidence"] = confidence_from_report(report)
            outcome.draft.current_version.quality = quality
        db.flush()

    return {
        "draft_id": outcome.draft.id,
        "accepted": outcome.accepted,
        "reason": outcome.reason,
    }


@job_handler("collect_analytics")
def collect_analytics(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Collect metrics for a published post.

    LinkedIn does not expose member post analytics to an ordinary integration,
    so unless an authorised API is configured this asks the user to enter the
    numbers rather than inventing them.
    """
    from app.database.models import PublishedPost
    from app.jobs.queue import enqueue

    post = db.get(PublishedPost, payload["published_post_id"])
    if post is None:
        return {"skipped": "post no longer exists"}

    existing = db.execute(
        select(AnalyticsSnapshot).where(AnalyticsSnapshot.published_post_id == post.id)
    ).scalars().first()

    if existing is None:
        notify(
            db,
            type=NotificationType.SYSTEM,
            title="Add metrics for your last post",
            body=f"How did '{post.content[:60]}…' do? Tap to enter the numbers.",
            priority=NotificationPriority.LOW,
            payload={"published_post_id": post.id, "action": "enter_metrics"},
            dedupe_key=f"metrics-request:{post.id}",
        )

    # Ask again in a week, when the post has finished accumulating.
    from datetime import timedelta

    enqueue(
        db,
        "generate_learning_report",
        {},
        run_at=utcnow() + timedelta(minutes=5),
        idempotency_key=f"learning:{post.id}",
    )
    return {"published_post_id": post.id, "requested_manual_entry": existing is None}


@job_handler("generate_learning_report")
def generate_learning_report(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from app.analytics.engine import compute_insights

    insights = compute_insights(db)
    return {"insights": len(insights)}


@job_handler("discover_connections")
def discover_connections(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Turn user-supplied people into scored recommendations.

    This never searches or scrapes LinkedIn. Candidates are supplied through
    the API by the user, and the user sends every invitation by hand.
    """
    from app.networking.service import CandidateInput, add_candidate, notify_new_candidates

    raw = payload.get("candidates") or []
    created = []
    for entry in raw[: int(payload.get("limit", 10))]:
        record = add_candidate(
            db,
            CandidateInput(
                name=entry.get("name", "").strip(),
                profile_url=entry.get("profile_url", "").strip(),
                role=entry.get("role"),
                company=entry.get("company"),
                context=entry.get("context", ""),
                shared_interests=entry.get("shared_interests"),
            ),
        )
        if record is not None:
            created.append(record)

    notify_new_candidates(db, created)
    return {"created": len(created)}


@job_handler("daily_loop")
def daily_loop(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Kick off discovery and re-arm itself for tomorrow."""
    from datetime import timedelta

    from app.core.settings_store import get_setting
    from app.jobs.queue import enqueue

    enqueue(
        db,
        "discover_topics",
        {},
        idempotency_key=f"discover:{utcnow().date().isoformat()}",
    )

    interval = float(get_setting(db, "discovery_interval_hours"))
    next_run = utcnow() + timedelta(hours=interval)
    enqueue(
        db,
        "daily_loop",
        {},
        run_at=next_run,
        idempotency_key=f"daily:{next_run.date().isoformat()}",
    )
    return {"next_run": next_run.isoformat()}
