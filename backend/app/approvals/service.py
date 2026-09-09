"""Approval recording and integrity enforcement.

Guarantees implemented here:

1. An approval is bound to an exact byte sequence (``approved_content_hash``).
2. Any later change to the draft's content invalidates outstanding approvals
   and returns the post to READY_FOR_REVIEW, cancelling any pending schedule.
3. A publish is only permitted when a *valid* approval's hash still equals the
   current version's hash.
4. Replaying the same client action (offline sync, retry) is a no-op.
"""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.approvals.state_machine import assert_transition
from app.content.text import canonicalize, char_count, content_hash, extract_hook, simhash_hex
from app.core.errors import (
    ApprovalInvalidError,
    ContentChangedError,
    NotFoundError,
    ValidationError,
)
from app.core.logging import log_event
from app.database.base import utcnow
from app.database.enums import (
    ApprovalAction,
    DraftStatus,
    ScheduleStatus,
    VersionOrigin,
)
from app.database.models import Approval, Draft, DraftVersion, ScheduledPost, StyleFeedback

log = logging.getLogger(__name__)


@dataclass
class DecisionResult:
    approval: Approval
    draft: Draft
    version: DraftVersion
    replayed: bool = False


# --------------------------------------------------------------------------
# Versions
# --------------------------------------------------------------------------


def add_version(
    db: Session,
    draft: Draft,
    content: str,
    *,
    label: str = "A",
    origin: VersionOrigin = VersionOrigin.LLM,
    quality: dict | None = None,
    fact_check: dict | None = None,
    notes: str | None = None,
    make_current: bool = True,
    invalidate_reason: str | None = "Content changed",
) -> DraftVersion:
    """Append a new immutable version. Never mutate an existing one."""
    text = canonicalize(content)
    if not text:
        raise ValidationError("A post cannot be empty.")

    version = DraftVersion(
        draft_id=draft.id,
        label=label,
        content=text,
        hook=extract_hook(text)[:500],
        char_count=char_count(text),
        content_hash=content_hash(text),
        simhash=simhash_hex(text),
        origin=origin,
        quality=quality,
        fact_check=fact_check,
        notes=notes,
    )
    db.add(version)
    db.flush()

    if make_current:
        previous_hash = draft.current_version.content_hash if draft.current_version else None
        # Assign the relationship (not just the FK) so the in-session object
        # stays consistent for callers that read draft.current_version next.
        draft.current_version = version
        # Only a genuine content change invalidates consent.
        if previous_hash is not None and previous_hash != version.content_hash:
            invalidate_approvals(db, draft, invalidate_reason or "Content changed")
    db.flush()
    return version


def invalidate_approvals(db: Session, draft: Draft, reason: str) -> int:
    """Void outstanding approvals and unwind anything they authorised."""
    approvals = (
        db.execute(
            select(Approval).where(
                Approval.draft_id == draft.id,
                Approval.valid.is_(True),
                Approval.action == ApprovalAction.APPROVE,
            )
        )
        .scalars()
        .all()
    )
    if not approvals:
        return 0

    now = utcnow()
    for approval in approvals:
        approval.valid = False
        approval.invalidated_at = now
        approval.invalidated_reason = reason

    pending = (
        db.execute(
            select(ScheduledPost).where(
                ScheduledPost.draft_id == draft.id,
                ScheduledPost.status == ScheduleStatus.PENDING,
            )
        )
        .scalars()
        .all()
    )
    for slot in pending:
        slot.status = ScheduleStatus.CANCELLED
        slot.last_error = reason

    if draft.status in {DraftStatus.APPROVED, DraftStatus.SCHEDULED}:
        draft.status = DraftStatus.READY_FOR_REVIEW

    db.flush()
    log_event(
        log,
        "APPROVAL_INVALIDATED",
        draft_id=draft.id,
        count=len(approvals),
        cancelled_schedules=len(pending),
        reason=reason,
    )
    return len(approvals)


# --------------------------------------------------------------------------
# Style signals
# --------------------------------------------------------------------------


def _phrase_diff(before: str, after: str) -> tuple[list[str], list[str]]:
    """Sentence-level diff: what the user deleted vs. what they wrote instead."""
    split = lambda t: [s.strip() for s in canonicalize(t).replace("\n", " ").split(". ") if s.strip()]
    a, b = split(before), split(after)
    matcher = difflib.SequenceMatcher(None, a, b)
    removed: list[str] = []
    added: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in {"replace", "delete"}:
            removed.extend(a[i1:i2])
        if tag in {"replace", "insert"}:
            added.extend(b[j1:j2])
    return removed[:20], added[:20]


def record_style_feedback(
    db: Session,
    *,
    kind: str,
    draft: Draft,
    before: str | None = None,
    after: str | None = None,
    reason: str | None = None,
    tags: list[str] | None = None,
) -> StyleFeedback:
    removed, added = ([], [])
    length_delta = None
    if before is not None and after is not None:
        removed, added = _phrase_diff(before, after)
        length_delta = char_count(after) - char_count(before)

    feedback = StyleFeedback(
        kind=kind,
        draft_id=draft.id,
        before_text=before,
        after_text=after,
        reason=reason,
        removed_phrases=removed,
        added_phrases=added,
        length_delta=length_delta,
        tags=tags or [],
    )
    db.add(feedback)
    db.flush()
    return feedback


# --------------------------------------------------------------------------
# Decisions
# --------------------------------------------------------------------------


def _find_replay(db: Session, client_action_id: str | None) -> Approval | None:
    if not client_action_id:
        return None
    return db.execute(
        select(Approval).where(Approval.client_action_id == client_action_id)
    ).scalar_one_or_none()


def submit_decision(
    db: Session,
    *,
    draft_id: int,
    device_id: str,
    action: ApprovalAction,
    expected_content_hash: str | None = None,
    edited_content: str | None = None,
    version_id: int | None = None,
    rejection_reason: str | None = None,
    note: str | None = None,
    client_action_id: str | None = None,
) -> DecisionResult:
    """Record an approve / reject / save-for-later decision.

    ``expected_content_hash`` is what the phone displayed. If the server's
    current content no longer matches, the decision is refused - this is what
    stops "approve one post, publish another", including after an offline
    queue is replayed late.
    """
    replay = _find_replay(db, client_action_id)
    if replay is not None:
        draft = db.get(Draft, replay.draft_id)
        version = db.get(DraftVersion, replay.version_id)
        log_event(log, "APPROVAL_REPLAY_IGNORED", draft_id=replay.draft_id, device_id=device_id)
        return DecisionResult(approval=replay, draft=draft, version=version, replayed=True)

    draft = db.get(Draft, draft_id)
    if draft is None:
        raise NotFoundError("That draft no longer exists.")

    # Pick the version being acted on: an explicit one, or whatever is current.
    if version_id is not None:
        version = db.get(DraftVersion, version_id)
        if version is None or version.draft_id != draft.id:
            raise NotFoundError("That version of the post no longer exists.")
        if draft.current_version_id != version.id:
            # Selecting variant B/C makes it current before it can be approved.
            draft.current_version = version
            db.flush()
    else:
        version = draft.current_version
    if version is None:
        raise NotFoundError("This draft has no content yet.")

    if expected_content_hash and expected_content_hash != version.content_hash:
        raise ContentChangedError(
            details={"expected": expected_content_hash, "actual": version.content_hash}
        )

    was_edited = False
    original_text = version.content

    if edited_content is not None and content_hash(edited_content) != version.content_hash:
        if action is not ApprovalAction.APPROVE:
            raise ValidationError("Edits can only be submitted together with an approval.")
        # The edit becomes a new version; the approval below binds to it.
        version = add_version(
            db,
            draft,
            edited_content,
            label=f"{version.label}-edited",
            origin=VersionOrigin.USER_EDIT,
            quality=version.quality,
            fact_check=version.fact_check,
            notes="Edited on device before approval",
            invalidate_reason="Edited by user before approval",
        )
        was_edited = True
        record_style_feedback(
            db, kind="edit", draft=draft, before=original_text, after=version.content
        )

    target = {
        ApprovalAction.APPROVE: DraftStatus.APPROVED,
        ApprovalAction.REJECT: DraftStatus.REJECTED,
        ApprovalAction.SAVE_FOR_LATER: DraftStatus.SAVED_FOR_LATER,
    }[action]
    assert_transition(DraftStatus(draft.status), target)

    approval = Approval(
        draft_id=draft.id,
        version_id=version.id,
        action=action,
        approved_content_hash=version.content_hash,
        approval_timestamp=utcnow(),
        device_id=device_id,
        valid=action is ApprovalAction.APPROVE,
        was_edited=was_edited,
        rejection_reason=rejection_reason,
        note=note,
        client_action_id=client_action_id,
    )
    db.add(approval)

    draft.status = target
    if action is ApprovalAction.REJECT:
        draft.rejection_reason = rejection_reason
        draft.rejection_note = note
        record_style_feedback(
            db, kind="reject", draft=draft, before=version.content, reason=rejection_reason
        )
    elif action is ApprovalAction.APPROVE:
        record_style_feedback(db, kind="approve", draft=draft, after=version.content)

    db.flush()
    log_event(
        log,
        {
            ApprovalAction.APPROVE: "POST_APPROVED",
            ApprovalAction.REJECT: "POST_REJECTED",
            ApprovalAction.SAVE_FOR_LATER: "POST_SAVED_FOR_LATER",
        }[action],
        draft_id=draft.id,
        version_id=version.id,
        device_id=device_id,
        edited=was_edited,
        reason=rejection_reason,
    )
    return DecisionResult(approval=approval, draft=draft, version=version)


# --------------------------------------------------------------------------
# Publish gate
# --------------------------------------------------------------------------


def valid_approval_for(db: Session, draft: Draft) -> Approval | None:
    """The newest approval that still matches the live content, or None.

    Consent is bound to *bytes*, not to a row id: if a later version happens to
    be byte-identical to what was approved, the approval still stands. Anything
    that actually changes the text produces a different hash and no match.
    """
    version = draft.current_version
    if version is None:
        return None
    return db.execute(
        select(Approval)
        .where(
            Approval.draft_id == draft.id,
            Approval.valid.is_(True),
            Approval.action == ApprovalAction.APPROVE,
            Approval.approved_content_hash == version.content_hash,
        )
        .order_by(Approval.id.desc())
    ).scalars().first()


def assert_publishable(db: Session, draft: Draft) -> tuple[Approval, DraftVersion]:
    """Raise unless this draft may legitimately be published right now."""
    if draft.status in {DraftStatus.REJECTED, DraftStatus.CANCELLED}:
        raise ApprovalInvalidError(
            "This post was rejected and can never be published.",
            code="draft_rejected",
            recovery="Generate a new draft instead.",
        )
    version = draft.current_version
    if version is None:
        raise ApprovalInvalidError("This draft has no content.")

    # Defence in depth: recompute the hash rather than trusting the stored one.
    if content_hash(version.content) != version.content_hash:
        raise ApprovalInvalidError(
            "Stored content does not match its hash.",
            code="content_hash_mismatch",
            recovery="Review and approve the post again.",
        )

    approval = valid_approval_for(db, draft)
    if approval is None:
        raise ApprovalInvalidError(
            "The content changed after it was approved, so publishing was blocked.",
            recovery="Review and approve the current version.",
        )
    return approval, version
