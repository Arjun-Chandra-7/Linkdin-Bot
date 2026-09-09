"""Posting calendar and slot allocation.

Posting days/times are configuration, never hard-coded. All arithmetic happens
in the user's local timezone (default Asia/Kolkata) and is stored as UTC, so a
"Wednesday 14:00" slot stays at 14:00 local across DST and restarts.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.approvals.state_machine import assert_transition
from app.core.errors import ConflictError
from app.core.logging import log_event
from app.core.settings_store import get_setting
from app.database.base import utcnow
from app.database.enums import DraftStatus, ScheduleStatus
from app.database.models import Approval, Draft, DraftVersion, PublishedPost, ScheduledPost

log = logging.getLogger(__name__)

_WEEKDAYS = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
_SEARCH_HORIZON_DAYS = 60


def get_timezone(db: Session) -> ZoneInfo:
    try:
        return ZoneInfo(get_setting(db, "timezone"))
    except Exception:  # pragma: no cover - bad user config
        log.warning("Unknown timezone configured; falling back to UTC")
        return ZoneInfo("UTC")


def _parse_slot(entry: dict) -> tuple[int, time] | None:
    weekday = _WEEKDAYS.get(str(entry.get("weekday", "")).upper()[:3])
    raw = str(entry.get("time", ""))
    try:
        hour, minute = (int(part) for part in raw.split(":")[:2])
        return (weekday, time(hour=hour, minute=minute)) if weekday is not None else None
    except (ValueError, TypeError):
        return None


def candidate_slots(db: Session, *, after: datetime | None = None, count: int = 20) -> list[datetime]:
    """Upcoming configured slots as UTC datetimes, soonest first."""
    tz = get_timezone(db)
    start = (after or utcnow()).astimezone(tz)
    parsed = [s for s in (_parse_slot(e) for e in get_setting(db, "posting_slots")) if s]
    if not parsed:
        return []

    results: list[datetime] = []
    day = start.date()
    for offset in range(_SEARCH_HORIZON_DAYS):
        current = day + timedelta(days=offset)
        for weekday, slot_time in parsed:
            if current.weekday() != weekday:
                continue
            local = datetime.combine(current, slot_time, tzinfo=tz)
            if local > start:
                results.append(local.astimezone(UTC))
        if len(results) >= count:
            break
    return sorted(results)[:count]


def _occupied_times(db: Session) -> list[datetime]:
    pending = db.execute(
        select(ScheduledPost.scheduled_at).where(
            ScheduledPost.status.in_([ScheduleStatus.PENDING, ScheduleStatus.PUBLISHING])
        )
    ).scalars().all()
    published = db.execute(
        select(PublishedPost.published_at).where(PublishedPost.published_at > utcnow() - timedelta(days=14))
    ).scalars().all()
    # UTCDateTime guarantees these come back timezone-aware.
    return [*pending, *published]


def next_available_slot(db: Session, *, after: datetime | None = None) -> datetime:
    """First configured slot that is free and respects the minimum gap."""
    min_gap = timedelta(hours=float(get_setting(db, "min_hours_between_posts")))
    taken = _occupied_times(db)

    for slot in candidate_slots(db, after=after, count=40):
        if all(abs(slot - t) >= min_gap for t in taken):
            return slot

    # No configured slot fits (e.g. slots removed): fall back to the minimum
    # gap after the last commitment rather than silently dropping the post.
    base = max([*taken, utcnow()]) if taken else utcnow()
    return base + min_gap


def schedule_approved_draft(
    db: Session,
    draft: Draft,
    version: DraftVersion,
    approval: Approval,
    *,
    requested_at: datetime | None = None,
) -> ScheduledPost:
    """Move an approved draft into the calendar.

    The idempotency key is derived from the approved content hash, so
    re-approving identical content can never create a second scheduled post.
    """
    key = f"draft:{draft.id}:hash:{approval.approved_content_hash[:24]}"
    existing = db.execute(
        select(ScheduledPost).where(ScheduledPost.idempotency_key == key)
    ).scalar_one_or_none()
    if existing is not None and existing.status in {ScheduleStatus.PENDING, ScheduleStatus.PUBLISHING}:
        return existing
    if existing is not None and existing.status == ScheduleStatus.PUBLISHED:
        raise ConflictError(
            "This exact post has already been published.",
            code="already_published",
            recovery="Edit the post if you want to publish something different.",
        )

    when = requested_at.astimezone(UTC) if requested_at else next_available_slot(db)
    if existing is not None:
        # A previously cancelled/failed slot for identical content is reused.
        existing.status = ScheduleStatus.PENDING
        existing.scheduled_at = when
        existing.version_id = version.id
        existing.approval_id = approval.id
        existing.last_error = None
        slot = existing
    else:
        slot = ScheduledPost(
            draft_id=draft.id,
            version_id=version.id,
            approval_id=approval.id,
            scheduled_at=when,
            timezone=get_setting(db, "timezone"),
            status=ScheduleStatus.PENDING,
            idempotency_key=key,
        )
        db.add(slot)

    assert_transition(DraftStatus(draft.status), DraftStatus.SCHEDULED)
    draft.status = DraftStatus.SCHEDULED
    draft.proposed_publish_at = when
    db.flush()

    from app.jobs.queue import enqueue

    enqueue(
        db,
        "publish_post",
        {"scheduled_post_id": slot.id},
        run_at=when,
        idempotency_key=f"publish:{slot.idempotency_key}",
    )
    log_event(log, "POST_SCHEDULED", draft_id=draft.id, scheduled_at=when.isoformat(), slot_id=slot.id)
    return slot


def cancel_schedule(db: Session, slot: ScheduledPost, reason: str) -> None:
    slot.status = ScheduleStatus.CANCELLED
    slot.last_error = reason
    db.flush()
    log_event(log, "SCHEDULE_CANCELLED", slot_id=slot.id, draft_id=slot.draft_id, reason=reason)
