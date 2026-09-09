"""The approval-integrity guarantees from the spec.

These are the tests that matter most: they are what stops the system from
publishing something the user did not agree to.
"""

from __future__ import annotations

import pytest

from app.approvals.service import (
    add_version,
    assert_publishable,
    submit_decision,
    valid_approval_for,
)
from app.core.errors import ApprovalInvalidError, ContentChangedError, InvalidTransitionError
from app.database.enums import ApprovalAction, DraftStatus, ScheduleStatus, VersionOrigin
from app.database.models import Approval, ScheduledPost


def test_approved_draft_is_publishable(db, make_draft):
    draft = make_draft()
    submit_decision(db, draft_id=draft.id, device_id="dev-1", action=ApprovalAction.APPROVE)
    db.commit()

    approval, version = assert_publishable(db, draft)
    assert approval.approved_content_hash == version.content_hash
    assert draft.status == DraftStatus.APPROVED


def test_editing_after_approval_blocks_publish_and_returns_to_review(db, make_draft):
    """draft A approved -> draft A modified -> attempt publish => BLOCK."""
    draft = make_draft()
    submit_decision(db, draft_id=draft.id, device_id="dev-1", action=ApprovalAction.APPROVE)
    db.commit()
    assert_publishable(db, draft)  # sanity: currently fine

    add_version(db, draft, "Completely different content that was never approved.")
    db.commit()

    assert draft.status == DraftStatus.READY_FOR_REVIEW
    assert valid_approval_for(db, draft) is None
    with pytest.raises(ApprovalInvalidError):
        assert_publishable(db, draft)


def test_edit_cancels_a_pending_schedule(db, make_draft):
    draft = make_draft()
    result = submit_decision(
        db, draft_id=draft.id, device_id="dev-1", action=ApprovalAction.APPROVE
    )
    db.commit()

    slot = ScheduledPost(
        draft_id=draft.id,
        version_id=result.version.id,
        approval_id=result.approval.id,
        scheduled_at=result.approval.approval_timestamp,
        idempotency_key=f"draft-{draft.id}-v{result.version.id}",
        status=ScheduleStatus.PENDING,
    )
    db.add(slot)
    draft.status = DraftStatus.SCHEDULED
    db.commit()

    add_version(db, draft, "Rewritten body after the schedule was created.")
    db.commit()

    assert slot.status == ScheduleStatus.CANCELLED
    assert draft.status == DraftStatus.READY_FOR_REVIEW


def test_stale_client_hash_is_refused(db, make_draft):
    """The phone approving what it *saw* must fail if the server moved on."""
    draft = make_draft()
    stale_hash = draft.current_version.content_hash
    add_version(db, draft, "Server-side regeneration happened while the phone was offline.")
    db.commit()

    with pytest.raises(ContentChangedError):
        submit_decision(
            db,
            draft_id=draft.id,
            device_id="dev-1",
            action=ApprovalAction.APPROVE,
            expected_content_hash=stale_hash,
        )


def test_rejected_draft_can_never_be_published(db, make_draft):
    draft = make_draft()
    submit_decision(
        db,
        draft_id=draft.id,
        device_id="dev-1",
        action=ApprovalAction.REJECT,
        rejection_reason="TOO_GENERIC",
    )
    db.commit()

    assert draft.status == DraftStatus.REJECTED
    with pytest.raises(ApprovalInvalidError):
        assert_publishable(db, draft)
    # And it cannot be walked back into an approvable state.
    with pytest.raises(InvalidTransitionError):
        submit_decision(db, draft_id=draft.id, device_id="dev-1", action=ApprovalAction.APPROVE)


def test_offline_replay_is_idempotent(db, make_draft):
    """Approve offline, reconnect, retry => one approval only."""
    draft = make_draft()
    first = submit_decision(
        db,
        draft_id=draft.id,
        device_id="dev-1",
        action=ApprovalAction.APPROVE,
        client_action_id="phone-action-42",
    )
    db.commit()
    second = submit_decision(
        db,
        draft_id=draft.id,
        device_id="dev-1",
        action=ApprovalAction.APPROVE,
        client_action_id="phone-action-42",
    )
    db.commit()

    assert second.replayed is True
    assert second.approval.id == first.approval.id
    assert db.query(Approval).filter(Approval.draft_id == draft.id).count() == 1


def test_edit_with_approval_creates_new_version_and_binds_to_it(db, make_draft):
    draft = make_draft()
    original_hash = draft.current_version.content_hash

    result = submit_decision(
        db,
        draft_id=draft.id,
        device_id="dev-1",
        action=ApprovalAction.APPROVE,
        expected_content_hash=original_hash,
        edited_content="I shipped the approval flow today.\n\nIt broke twice, both times on the hash check.",
    )
    db.commit()

    assert result.approval.was_edited is True
    assert result.version.origin == VersionOrigin.USER_EDIT
    assert result.approval.approved_content_hash == result.version.content_hash
    assert result.approval.approved_content_hash != original_hash
    assert draft.status == DraftStatus.APPROVED
    assert_publishable(db, draft)  # the edited text is what is authorised


def test_cosmetic_whitespace_does_not_invalidate_approval(db, make_draft):
    draft = make_draft()
    text = draft.current_version.content
    submit_decision(db, draft_id=draft.id, device_id="dev-1", action=ApprovalAction.APPROVE)
    db.commit()

    add_version(db, draft, text + "   \n\n\n")
    db.commit()

    assert draft.status == DraftStatus.APPROVED
    assert valid_approval_for(db, draft) is not None


def test_tampered_stored_content_blocks_publish(db, make_draft):
    """If the row is edited out-of-band, the recomputed hash catches it."""
    draft = make_draft()
    submit_decision(db, draft_id=draft.id, device_id="dev-1", action=ApprovalAction.APPROVE)
    db.commit()

    draft.current_version.content = "Tampered content injected directly into the database."
    db.commit()

    with pytest.raises(ApprovalInvalidError):
        assert_publishable(db, draft)
