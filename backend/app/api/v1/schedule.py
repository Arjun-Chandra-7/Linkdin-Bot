"""Posting calendar."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.schemas import CalendarEntry, ScheduledPostOut
from app.core.errors import ConflictError, NotFoundError
from app.core.logging import log_event
from app.database.enums import DraftStatus, PublishMethod, ScheduleStatus
from app.database.models import Device, Draft, DraftVersion, PublishedPost, ScheduledPost
from app.database.session import get_db
from app.scheduler.service import cancel_schedule, next_available_slot
from app.security.auth import get_current_device

log = logging.getLogger(__name__)
router = APIRouter(prefix="/schedule", tags=["schedule"])


@router.get("", response_model=list[ScheduledPostOut])
def list_schedule(
    include_done: bool = False,
    db: Session = Depends(get_db),
    _: Device = Depends(get_current_device),
) -> list[ScheduledPostOut]:
    statuses = (
        list(ScheduleStatus)
        if include_done
        else [ScheduleStatus.PENDING, ScheduleStatus.PUBLISHING]
    )
    rows = (
        db.execute(
            select(ScheduledPost)
            .where(ScheduledPost.status.in_(statuses))
            .order_by(ScheduledPost.scheduled_at)
        )
        .scalars()
        .all()
    )
    out: list[ScheduledPostOut] = []
    for slot in rows:
        draft = db.get(Draft, slot.draft_id)
        item = ScheduledPostOut.model_validate(slot)
        if draft is not None:
            item.title = draft.title
            item.post_type = draft.post_type
        out.append(item)
    return out


@router.get("/calendar", response_model=list[CalendarEntry])
def calendar(
    limit: int = Query(default=100, le=300),
    db: Session = Depends(get_db),
    _: Device = Depends(get_current_device),
) -> list[CalendarEntry]:
    """Everything with a place on the calendar, in one list for the app."""
    entries: list[CalendarEntry] = []
    drafts = (
        db.execute(select(Draft).order_by(Draft.updated_at.desc()).limit(limit)).scalars().all()
    )
    for draft in drafts:
        slot = (
            db.execute(
                select(ScheduledPost)
                .where(ScheduledPost.draft_id == draft.id)
                .order_by(ScheduledPost.id.desc())
            )
            .scalars()
            .first()
        )
        published = db.execute(
            select(PublishedPost).where(PublishedPost.draft_id == draft.id)
        ).scalar_one_or_none()
        entries.append(
            CalendarEntry(
                draft_id=draft.id,
                slot_id=slot.id if slot else None,
                title=draft.title,
                post_type=draft.post_type,
                status=draft.status,
                scheduled_at=slot.scheduled_at if slot else draft.proposed_publish_at,
                published_at=published.published_at if published else None,
                schedule_status=slot.status if slot else None,
            )
        )
    return entries


@router.get("/next-slot")
def next_slot(
    db: Session = Depends(get_db), _: Device = Depends(get_current_device)
) -> dict[str, str | None]:
    slot = next_available_slot(db)
    return {"next_available_slot": slot.isoformat()}


def _get_slot(db: Session, slot_id: int) -> ScheduledPost:
    slot = db.get(ScheduledPost, slot_id)
    if slot is None:
        raise NotFoundError("That scheduled post no longer exists.")
    return slot


@router.post("/{slot_id}/confirm-published", response_model=ScheduledPostOut)
def confirm_published(
    slot_id: int,
    external_url: str | None = None,
    db: Session = Depends(get_db),
    device: Device = Depends(get_current_device),
) -> ScheduledPostOut:
    """Manual mode: the user posted it on LinkedIn and is confirming here."""
    slot = _get_slot(db, slot_id)
    if slot.status == ScheduleStatus.PUBLISHED:
        raise ConflictError(
            "This post is already recorded as published.",
            code="already_published",
            recovery="Pull to refresh.",
        )

    draft = db.get(Draft, slot.draft_id)
    version = db.get(DraftVersion, slot.version_id)
    if draft is None or version is None:
        raise NotFoundError("The post behind this schedule no longer exists.")

    from app.jobs.handlers import record_publication

    record_publication(
        db,
        draft=draft,
        slot=slot,
        version=version,
        approval_id=slot.approval_id,
        method=PublishMethod.MANUAL,
        external_url=external_url,
    )
    db.commit()
    log_event(log, "MANUAL_PUBLISH_CONFIRMED", draft_id=draft.id, device_id=device.id)
    return ScheduledPostOut.model_validate(slot)


@router.post("/{slot_id}/reschedule", response_model=ScheduledPostOut)
def reschedule(
    slot_id: int,
    scheduled_at: datetime,
    db: Session = Depends(get_db),
    _: Device = Depends(get_current_device),
) -> ScheduledPostOut:
    slot = _get_slot(db, slot_id)
    if slot.status not in {ScheduleStatus.PENDING, ScheduleStatus.FAILED}:
        raise ConflictError("Only a pending or failed post can be rescheduled.")
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=UTC)
    else:
        scheduled_at = scheduled_at.astimezone(UTC)

    slot.scheduled_at = scheduled_at
    slot.status = ScheduleStatus.PENDING

    from app.jobs.queue import enqueue

    enqueue(
        db,
        "publish_post",
        {"scheduled_post_id": slot.id},
        run_at=scheduled_at,
        idempotency_key=f"publish:{slot.idempotency_key}",
    )
    draft = db.get(Draft, slot.draft_id)
    if draft is not None:
        draft.proposed_publish_at = scheduled_at
        if draft.status == DraftStatus.FAILED:
            draft.status = DraftStatus.SCHEDULED
    db.commit()
    log_event(log, "POST_RESCHEDULED", slot_id=slot.id, scheduled_at=scheduled_at.isoformat())
    return ScheduledPostOut.model_validate(slot)


@router.delete("/{slot_id}", response_model=ScheduledPostOut)
def cancel(
    slot_id: int,
    db: Session = Depends(get_db),
    _: Device = Depends(get_current_device),
) -> ScheduledPostOut:
    slot = _get_slot(db, slot_id)
    cancel_schedule(db, slot, "Cancelled from the app")
    draft = db.get(Draft, slot.draft_id)
    if draft is not None and draft.status in {DraftStatus.SCHEDULED, DraftStatus.PUBLISHING}:
        draft.status = DraftStatus.CANCELLED
    db.commit()
    return ScheduledPostOut.model_validate(slot)
