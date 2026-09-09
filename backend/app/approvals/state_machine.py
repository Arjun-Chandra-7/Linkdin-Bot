"""Server-side draft state machine.

Transitions are validated here and nowhere else, so no code path can move a
post into PUBLISHED without passing through approval and scheduling.

REJECTED and CANCELLED are terminal by design: a rejected draft can never be
published. Regenerating after a rejection produces a *new* draft, which must be
approved on its own merits.
"""

from __future__ import annotations

from app.core.errors import InvalidTransitionError
from app.database.enums import DraftStatus as S

ALLOWED: dict[S, frozenset[S]] = {
    S.DRAFT: frozenset({S.QUALITY_CHECK, S.CANCELLED, S.FAILED}),
    S.QUALITY_CHECK: frozenset({S.READY_FOR_REVIEW, S.REJECTED, S.DRAFT, S.FAILED, S.CANCELLED}),
    S.READY_FOR_REVIEW: frozenset(
        {S.APPROVED, S.REJECTED, S.SAVED_FOR_LATER, S.DRAFT, S.CANCELLED}
    ),
    S.SAVED_FOR_LATER: frozenset(
        {S.READY_FOR_REVIEW, S.APPROVED, S.REJECTED, S.DRAFT, S.CANCELLED}
    ),
    # An approval can be invalidated by an edit, which sends the post back for
    # review rather than letting stale consent stand.
    S.APPROVED: frozenset({S.SCHEDULED, S.READY_FOR_REVIEW, S.REJECTED, S.CANCELLED}),
    S.SCHEDULED: frozenset({S.PUBLISHING, S.READY_FOR_REVIEW, S.CANCELLED, S.FAILED}),
    # Manual mode parks here while the user posts; they can also abandon it.
    S.PUBLISHING: frozenset({S.PUBLISHED, S.FAILED, S.CANCELLED}),
    S.PUBLISHED: frozenset(),
    S.REJECTED: frozenset(),
    S.CANCELLED: frozenset(),
    S.FAILED: frozenset({S.SCHEDULED, S.READY_FOR_REVIEW, S.CANCELLED}),
}

TERMINAL: frozenset[S] = frozenset({S.PUBLISHED, S.REJECTED, S.CANCELLED})


def can_transition(current: S, target: S) -> bool:
    return target in ALLOWED.get(S(current), frozenset())


def assert_transition(current: S, target: S) -> None:
    if not can_transition(current, target):
        raise InvalidTransitionError(
            f"Cannot move a post from {current} to {target}.",
            details={"from": str(current), "to": str(target)},
        )


def is_terminal(status: S) -> bool:
    return S(status) in TERMINAL
