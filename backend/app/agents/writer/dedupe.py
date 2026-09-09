"""Repetition detection.

Before a draft is recommended it is compared against what has already been
published and against other recent drafts, so the same insight is not posted
twice in slightly different words.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.content.text import similarity
from app.database.enums import DraftStatus
from app.database.models import Draft, DraftVersion, PublishedPost


@dataclass
class DuplicateMatch:
    kind: str  # published | draft
    reference_id: int
    score: float
    title: str | None = None


def find_duplicate(
    db: Session,
    content: str,
    *,
    threshold: float,
    exclude_draft_id: int | None = None,
    published_limit: int = 60,
    draft_limit: int = 40,
) -> DuplicateMatch | None:
    """Closest prior post above the similarity threshold, if any."""
    best: DuplicateMatch | None = None

    published = (
        db.execute(select(PublishedPost).order_by(PublishedPost.id.desc()).limit(published_limit))
        .scalars()
        .all()
    )
    for post in published:
        score = similarity(content, post.content)
        if score >= threshold and (best is None or score > best.score):
            best = DuplicateMatch(kind="published", reference_id=post.draft_id, score=score)

    live_statuses = [
        DraftStatus.READY_FOR_REVIEW,
        DraftStatus.SAVED_FOR_LATER,
        DraftStatus.APPROVED,
        DraftStatus.SCHEDULED,
    ]
    drafts = (
        db.execute(
            select(Draft)
            .where(Draft.status.in_(live_statuses))
            .order_by(Draft.id.desc())
            .limit(draft_limit)
        )
        .scalars()
        .all()
    )
    for draft in drafts:
        if exclude_draft_id is not None and draft.id == exclude_draft_id:
            continue
        version = draft.current_version
        if version is None:
            continue
        score = similarity(content, version.content)
        if score >= threshold and (best is None or score > best.score):
            best = DuplicateMatch(
                kind="draft", reference_id=draft.id, score=score, title=draft.title
            )

    return best


def hook_recently_used(db: Session, hook: str, *, lookback: int = 10, threshold: float = 0.8) -> bool:
    """Guard against reusing the same opening line shape."""
    if not hook:
        return False
    recent_hooks = (
        db.execute(select(DraftVersion.hook).order_by(DraftVersion.id.desc()).limit(lookback))
        .scalars()
        .all()
    )
    return any(h and similarity(hook, h) >= threshold for h in recent_hooks)
