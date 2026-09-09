"""Draft browsing and editing."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.v1.deps import count_where, draft_detail, draft_summary
from app.api.v1.schemas import (
    DraftDetail,
    DraftListResponse,
    DraftVersionOut,
    RewriteOperation,
    SaveEditRequest,
)
from app.approvals.service import add_version
from app.content.text import content_hash
from app.core.errors import ContentChangedError, NotFoundError, ValidationError
from app.core.logging import log_event
from app.database.enums import ContentCategory, DraftStatus, PostType, VersionOrigin
from app.database.models import Device, Draft
from app.database.session import get_db
from app.security.auth import get_current_device

log = logging.getLogger(__name__)
router = APIRouter(prefix="/drafts", tags=["drafts"])

# What the approval queue shows by default.
REVIEW_STATUSES = [DraftStatus.READY_FOR_REVIEW, DraftStatus.SAVED_FOR_LATER]


@router.get("", response_model=DraftListResponse)
def list_drafts(
    status: list[DraftStatus] | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    db: Session = Depends(get_db),
    _: Device = Depends(get_current_device),
) -> DraftListResponse:
    statuses = status or REVIEW_STATUSES
    condition = Draft.status.in_(statuses)
    rows = (
        db.execute(
            select(Draft)
            .where(condition)
            .order_by(desc(Draft.updated_at))
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return DraftListResponse(
        items=[draft_summary(d) for d in rows],
        total=count_where(db, Draft, condition),
    )


def _get_draft(db: Session, draft_id: int) -> Draft:
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise NotFoundError("That draft no longer exists.")
    return draft


@router.get("/{draft_id}", response_model=DraftDetail)
def get_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    _: Device = Depends(get_current_device),
) -> DraftDetail:
    return draft_detail(db, _get_draft(db, draft_id))


@router.post("/{draft_id}/versions/{version_id}/select", response_model=DraftDetail)
def select_version(
    draft_id: int,
    version_id: int,
    db: Session = Depends(get_db),
    _: Device = Depends(get_current_device),
) -> DraftDetail:
    """Choose variant A/B/C as the one under review."""
    draft = _get_draft(db, draft_id)
    version = next((v for v in draft.versions if v.id == version_id), None)
    if version is None:
        raise NotFoundError("That version no longer exists.")
    if draft.current_version_id != version.id:
        previous = draft.current_version
        draft.current_version = version
        if previous is not None and previous.content_hash != version.content_hash:
            from app.approvals.service import invalidate_approvals

            invalidate_approvals(db, draft, "A different variant was selected")
    db.commit()
    return draft_detail(db, draft)


@router.put("/{draft_id}/content", response_model=DraftVersionOut)
def save_edit(
    draft_id: int,
    payload: SaveEditRequest,
    db: Session = Depends(get_db),
    device: Device = Depends(get_current_device),
) -> DraftVersionOut:
    """Persist a manual edit without approving it yet.

    Manual edits are never overwritten by the system; only an explicit
    regenerate request replaces them.
    """
    draft = _get_draft(db, draft_id)
    current = draft.current_version
    if (
        current is not None
        and payload.expected_content_hash
        and payload.expected_content_hash != current.content_hash
    ):
        raise ContentChangedError(
            details={"expected": payload.expected_content_hash, "actual": current.content_hash}
        )
    if current is not None and content_hash(payload.content) == current.content_hash:
        return DraftVersionOut.model_validate(current)

    version = add_version(
        db,
        draft,
        payload.content,
        label=f"{current.label}-edited" if current else "edited",
        origin=VersionOrigin.USER_EDIT,
        quality=current.quality if current else None,
        fact_check=current.fact_check if current else None,
        notes="Manual edit saved from the device",
        invalidate_reason="Edited by user",
    )
    # A saved edit needs fresh eyes before it can be approved.
    if draft.status == DraftStatus.SAVED_FOR_LATER:
        draft.status = DraftStatus.READY_FOR_REVIEW
    db.commit()
    log_event(log, "DRAFT_EDITED", draft_id=draft.id, device_id=device.id, version_id=version.id)
    return DraftVersionOut.model_validate(version)


class ManualIdeaRequest(BaseModel):
    """The user's own note - the highest-value source there is."""

    topic: str = Field(min_length=3, max_length=500)
    notes: str = Field(default="", max_length=4000)
    category: ContentCategory = ContentCategory.BUILD_LOG
    post_type: PostType | None = None
    generate_now: bool = True
    scheduled_at: datetime | None = None


@router.post("/from-idea", response_model=DraftDetail | dict)
def create_from_idea(
    payload: ManualIdeaRequest,
    db: Session = Depends(get_db),
    device: Device = Depends(get_current_device),
):
    """Turn a note the user typed into a scored idea, and optionally draft it."""
    from app.agents.discovery.idea_engine import fingerprint, score_item
    from app.agents.discovery.sources import RawItem
    from app.database.enums import IdeaStatus
    from app.database.models import Idea

    item = RawItem(title=payload.topic, summary=payload.notes, category=payload.category)
    scores = score_item(item)
    # A topic the user typed themselves is by definition relevant to them.
    scores["personal_experience_score"] = max(scores["personal_experience_score"], 0.9)
    scores["final_score"] = max(scores["final_score"], 0.8)

    idea = Idea(
        topic=payload.topic,
        summary=payload.notes or None,
        category=payload.category,
        status=IdeaStatus.SCORED,
        fingerprint=fingerprint(payload.topic),
        why_it_matters="Added directly by the author.",
        extra={"post_type": payload.post_type.value} if payload.post_type else {},
        **scores,
    )
    db.add(idea)
    db.flush()

    if not payload.generate_now:
        from app.jobs.queue import enqueue

        enqueue(db, "research_topic", {"idea_id": idea.id}, idempotency_key=f"research:{idea.id}")
        db.commit()
        return {"idea_id": idea.id, "queued": True}

    from app.agents.writer.agent import generate_drafts

    outcome = generate_drafts(db, idea)
    if outcome.draft is not None and payload.scheduled_at is not None:
        when = payload.scheduled_at
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        else:
            when = when.astimezone(UTC)
        outcome.draft.proposed_publish_at = when
    db.commit()
    log_event(log, "MANUAL_IDEA_SUBMITTED", idea_id=idea.id, device_id=device.id)
    if outcome.draft is None:
        raise NotFoundError("No draft could be produced from that idea.")
    return draft_detail(db, outcome.draft)


@router.post("/{draft_id}/rewrite", response_model=DraftDetail)
def rewrite_draft(
    draft_id: int,
    payload: RewriteOperation,
    db: Session = Depends(get_db),
    device: Device = Depends(get_current_device),
) -> DraftDetail:
    """Targeted rewrite: shorten, expand, change register, redo the hook.

    This replaces the current text, so any existing approval is invalidated -
    a regenerated post has to be approved again.
    """
    from app.agents.writer.agent import rewrite as run_rewrite

    draft = _get_draft(db, draft_id)
    try:
        run_rewrite(
            db,
            draft,
            operation=payload.operation,
            instruction=payload.instruction,
            paragraph_index=payload.paragraph_index,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    db.commit()
    log_event(log, "DRAFT_REWRITE_REQUESTED", draft_id=draft.id, device_id=device.id)
    return draft_detail(db, draft)
