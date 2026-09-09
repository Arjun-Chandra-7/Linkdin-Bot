"""Approval submission - the single write path for human decisions."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.schemas import ApprovalRequest, ApprovalResponse
from app.approvals.service import submit_decision
from app.core.errors import ValidationError
from app.database.enums import ApprovalAction
from app.database.models import Approval, Device
from app.database.session import get_db
from app.security.auth import get_current_device

log = logging.getLogger(__name__)
router = APIRouter(prefix="/approvals", tags=["approvals"])


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
