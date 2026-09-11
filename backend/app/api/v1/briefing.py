"""Spoken briefings.

Jarvis reads these aloud, so the text is written to be *heard*: short
sentences, no markdown, no raw enum names, and numbers rounded to something a
person would actually say. Nothing here invents a figure - if a metric was
never collected it is simply left out of the sentence.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.engine import latest_snapshot
from app.database.base import utcnow
from app.database.enums import ConfidenceLevel, ConnectionStatus, DraftStatus, ScheduleStatus
from app.database.models import (
    ConnectionCandidate,
    Device,
    Draft,
    LearningInsight,
    PublishedPost,
    ScheduledPost,
)
from app.database.session import get_db
from app.scheduler.service import get_timezone
from app.security.auth import get_current_device

log = logging.getLogger(__name__)
router = APIRouter(prefix="/briefing", tags=["briefing"])

REVIEW_STATUSES = [DraftStatus.READY_FOR_REVIEW, DraftStatus.SAVED_FOR_LATER]


class Briefing(BaseModel):
    """A spoken summary plus the same facts as data, for the GUI."""

    speech: str
    headline: str
    pending_approvals: int
    scheduled_posts: int
    published_total: int
    published_this_week: int
    posts_with_metrics: int
    total_reactions: int | None = None
    total_impressions: int | None = None
    next_scheduled_at: str | None = None
    next_scheduled_title: str | None = None
    top_insight: str | None = None
    connections_to_review: int = 0


def _count(db: Session, model, *conditions) -> int:
    stmt = select(func.count()).select_from(model)
    if conditions:
        stmt = stmt.where(*conditions)
    return int(db.execute(stmt).scalar_one())


def _spoken_when(when, tz) -> str:
    local = when.astimezone(tz)
    today = utcnow().astimezone(tz).date()
    delta = (local.date() - today).days
    time_part = local.strftime("%-I:%M %p").lower().replace(":00", "")
    if delta == 0:
        return f"today at {time_part}"
    if delta == 1:
        return f"tomorrow at {time_part}"
    if 2 <= delta <= 6:
        return f"{local.strftime('%A')} at {time_part}"
    return f"{local.strftime('%A the %-d')} at {time_part}"


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def build_briefing(db: Session) -> Briefing:
    tz = get_timezone(db)
    week_ago = utcnow() - timedelta(days=7)

    pending = _count(db, Draft, Draft.status.in_(REVIEW_STATUSES))
    scheduled = _count(db, ScheduledPost, ScheduledPost.status == ScheduleStatus.PENDING)
    published_total = _count(db, PublishedPost)
    published_week = _count(db, PublishedPost, PublishedPost.published_at >= week_ago)
    connections = _count(
        db, ConnectionCandidate, ConnectionCandidate.status == ConnectionStatus.NEW
    )

    posts = db.execute(select(PublishedPost)).scalars().all()
    reactions = 0
    impressions = 0
    with_metrics = 0
    for post in posts:
        snapshot = latest_snapshot(db, post.id)
        if snapshot is None:
            continue
        if snapshot.reactions is None and snapshot.impressions is None:
            continue
        with_metrics += 1
        reactions += snapshot.reactions or 0
        impressions += snapshot.impressions or 0

    next_slot = db.execute(
        select(ScheduledPost)
        .where(ScheduledPost.status == ScheduleStatus.PENDING)
        .order_by(ScheduledPost.scheduled_at)
        .limit(1)
    ).scalars().first()
    next_title = None
    if next_slot is not None:
        draft = db.get(Draft, next_slot.draft_id)
        next_title = draft.title if draft else None

    insight = db.execute(
        select(LearningInsight)
        .where(LearningInsight.confidence != ConfidenceLevel.INSUFFICIENT_DATA)
        .order_by(LearningInsight.sample_size.desc())
        .limit(1)
    ).scalars().first()

    # ---- Compose something that sounds right read aloud ----------------
    parts: list[str] = []
    if pending:
        parts.append(f"You have {_plural(pending, 'draft')} waiting for approval")
    else:
        parts.append("Nothing is waiting for your approval")

    if next_slot is not None:
        when = _spoken_when(next_slot.scheduled_at, tz)
        if next_title:
            parts.append(f"Next out is \"{next_title}\", {when}")
        else:
            parts.append(f"The next post goes out {when}")
    elif scheduled:
        parts.append(f"{_plural(scheduled, 'post')} scheduled")

    if published_total == 0:
        parts.append("Nothing has been published yet")
    else:
        published_line = f"You've published {_plural(published_total, 'post')} in total"
        if published_week:
            published_line += f", {published_week} this week"
        parts.append(published_line)

        if with_metrics:
            metric_bits = []
            if impressions:
                metric_bits.append(f"{impressions:,} impressions")
            if reactions:
                metric_bits.append(f"{reactions:,} reactions")
            if metric_bits:
                parts.append(
                    "Across the "
                    + _plural(with_metrics, "post")
                    + " with numbers recorded, that's "
                    + " and ".join(metric_bits)
                )
        else:
            parts.append("No metrics have been entered yet, so I can't tell you how they did")

    if insight is not None:
        parts.append(insight.statement.rstrip("."))

    if connections:
        parts.append(f"{_plural(connections, 'person', 'people')} worth connecting with")

    headline = (
        f"{pending} to review · {scheduled} scheduled · {published_total} published"
    )

    return Briefing(
        speech=". ".join(parts) + ".",
        headline=headline,
        pending_approvals=pending,
        scheduled_posts=scheduled,
        published_total=published_total,
        published_this_week=published_week,
        posts_with_metrics=with_metrics,
        total_reactions=reactions if with_metrics else None,
        total_impressions=impressions if with_metrics else None,
        next_scheduled_at=next_slot.scheduled_at.isoformat() if next_slot else None,
        next_scheduled_title=next_title,
        top_insight=insight.statement if insight else None,
        connections_to_review=connections,
    )


@router.get("", response_model=Briefing)
def briefing(
    db: Session = Depends(get_db), _: Device = Depends(get_current_device)
) -> Briefing:
    return build_briefing(db)
