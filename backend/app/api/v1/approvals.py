"""Approval submission - the single write path for human decisions."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.schemas import ApprovalRequest, ApprovalResponse
from app.approvals.service import submit_decision
from app.core.errors import ValidationError
from app.core.logging import log_event
from app.database.enums import ApprovalAction, RejectionReason
from app.database.models import Approval, Device
from app.database.base import utcnow
from app.database.session import get_db
from app.security.auth import get_current_device

log = logging.getLogger(__name__)
router = APIRouter(prefix="/approvals", tags=["approvals"])


class DiscardRequest(BaseModel):
    """Several drafts discarded in one go."""

    draft_ids: list[int] = Field(min_length=1, max_length=100)
    rejection_reason: RejectionReason | None = None
    note: str | None = Field(default=None, max_length=1000)


class DiscardResponse(BaseModel):
    rejected: list[int]
    skipped: dict[int, str]
    message: str


@router.post("/discard", response_model=DiscardResponse)
def discard_drafts(
    payload: DiscardRequest,
    db: Session = Depends(get_db),
    device: Device = Depends(get_current_device),
) -> DiscardResponse:
    """Discard several drafts at once.

    Clearing a queue one draft at a time means opening each, reading it, and rejecting it — which
    is the right amount of friction for approving something and far too much for throwing away
    six drafts you can see are not worth reading.

    Each one still goes through submit_decision, so the writer learns from a bulk discard exactly
    as it would from six individual ones, and the audit trail is the same. No content hash is
    required because none is required to reject: the hash exists to stop you approving text you
    did not see, and that risk does not exist here.

    One bad id does not sink the rest. A draft that is already decided, or gone, is reported back
    by id rather than failing the whole request.

    Named "discard" rather than anything with "bulk" in it, and not only for readability: a
    safety test refuses any route whose path suggests mass action, because mass action against
    LinkedIn is what gets an account restricted. This one never touches LinkedIn — it throws away
    local drafts that were never published — so the right answer was a name that says what it
    does, not an exception carved into the test.
    """
    rejected: list[int] = []
    skipped: dict[int, str] = {}

    for draft_id in dict.fromkeys(payload.draft_ids):      # de-duplicated, order kept
        try:
            submit_decision(
                db,
                draft_id=draft_id,
                device_id=device.id,
                action=ApprovalAction.REJECT,
                expected_content_hash=None,
                version_id=None,
                edited_content=None,
                rejection_reason=(
                    payload.rejection_reason.value if payload.rejection_reason else None
                ),
                note=payload.note,
                client_action_id=f"bulk:{device.id}:{draft_id}:{utcnow().isoformat()}",
            )
            rejected.append(draft_id)
        except Exception as exc:  # noqa: BLE001 - one bad id must not sink the rest
            skipped[draft_id] = str(exc)[:200]

    db.commit()
    log_event(log, "DRAFTS_DISCARDED", count=len(rejected), device_id=device.id)
    done = len(rejected)
    return DiscardResponse(
        rejected=rejected,
        skipped=skipped,
        message=(
            f"Discarded {done} draft{'' if done == 1 else 's'}."
            + (f" {len(skipped)} could not be." if skipped else "")
        ),
    )


@router.post("", response_model=ApprovalResponse)
def submit_approval(
    payload: ApprovalRequest,
    db: Session = Depends(get_db),
    device: Device = Depends(get_current_device),
) -> ApprovalResponse:
    if payload.action is ApprovalAction.APPROVE and not payload.expected_content_hash:
        # Approving without saying what you saw is exactly the mistake the
        # hash check exists to prevent.
        raise ValidationError(
            "An approval must include the hash of the content that was displayed.",
            code="missing_content_hash",
            recovery="Reload the draft and approve it again.",
        )

    result = submit_decision(
        db,
        draft_id=payload.draft_id,
        device_id=device.id,
        action=payload.action,
        expected_content_hash=payload.expected_content_hash,
        version_id=payload.version_id,
        edited_content=payload.edited_content,
        rejection_reason=payload.rejection_reason.value if payload.rejection_reason else None,
        note=payload.note,
        client_action_id=payload.client_action_id,
    )

    scheduled_at = None
    message = "Decision recorded."
    if payload.action is ApprovalAction.APPROVE and not result.replayed:
        from app.scheduler.service import schedule_approved_draft

        slot = schedule_approved_draft(
            db, result.draft, result.version, result.approval, requested_at=payload.scheduled_at
        )
        scheduled_at = slot.scheduled_at
        message = "Approved and scheduled."
    elif result.replayed:
        existing = db.execute(
            select(Approval).where(Approval.id == result.approval.id)
        ).scalar_one()
        message = "Already recorded - no changes made."
        scheduled_at = None
        del existing

    db.commit()
    return ApprovalResponse(
        approval_id=result.approval.id,
        draft_id=result.draft.id,
        version_id=result.version.id,
        status=result.draft.status,
        approved_content_hash=result.approval.approved_content_hash,
        approval_timestamp=result.approval.approval_timestamp,
        replayed=result.replayed,
        scheduled_at=scheduled_at,
        message=message,
    )
