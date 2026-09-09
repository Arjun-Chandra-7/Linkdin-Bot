"""Analytics and learned insights."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.engine import compute_insights, latest_snapshot
from app.api.v1.schemas import (
    AnalyticsOverview,
    InsightOut,
    MetricsInput,
    PostMetrics,
)
from app.core.errors import NotFoundError
from app.core.logging import log_event
from app.database.base import utcnow
from app.database.enums import ConfidenceLevel
from app.database.models import (
    AnalyticsSnapshot,
    Device,
    Draft,
    LearningInsight,
    PublishedPost,
)
from app.database.session import get_db
from app.security.auth import get_current_device

log = logging.getLogger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])


def _post_metrics(db: Session, post: PublishedPost) -> PostMetrics:
    snapshot = latest_snapshot(db, post.id)
    draft = db.get(Draft, post.draft_id)
    return PostMetrics(
        published_post_id=post.id,
        draft_id=post.draft_id,
        title=draft.title if draft else post.content[:80],
        post_type=post.post_type,
        published_at=post.published_at,
        impressions=snapshot.impressions if snapshot else None,
        reactions=snapshot.reactions if snapshot else None,
        comments=snapshot.comments if snapshot else None,
        reposts=snapshot.reposts if snapshot else None,
        clicks=snapshot.clicks if snapshot else None,
        followers_gained=snapshot.followers_gained if snapshot else None,
        has_data=snapshot is not None,
    )


@router.get("/overview", response_model=AnalyticsOverview)
def overview(
    db: Session = Depends(get_db), _: Device = Depends(get_current_device)
) -> AnalyticsOverview:
    """Real numbers only. With no published posts the app shows an empty state."""
    posts = (
        db.execute(select(PublishedPost).order_by(PublishedPost.published_at.desc()).limit(50))
        .scalars()
        .all()
    )
    metrics = [_post_metrics(db, post) for post in posts]
    with_data = [m for m in metrics if m.has_data]

    insights = (
        db.execute(
            select(LearningInsight)
            .where(LearningInsight.confidence != ConfidenceLevel.INSUFFICIENT_DATA)
            .order_by(LearningInsight.sample_size.desc())
            .limit(10)
        )
        .scalars()
        .all()
    )

    best_format = None
    format_insight = next(
        (i for i in insights if i.dimension == "post_type" and (i.lift or 0) > 0), None
    )
    if format_insight is not None:
        best_format = format_insight.segment

    empty_state = None
    if not posts:
        empty_state = "No analytics yet. Publish your first post to begin learning."
    elif not with_data:
        empty_state = (
            "No metrics recorded yet. Add the numbers from LinkedIn for a published "
            "post and patterns will start to appear."
        )

    return AnalyticsOverview(
        published_count=len(posts),
        posts_with_metrics=len(with_data),
        insights=[InsightOut.model_validate(i) for i in insights],
        best_format=best_format,
        empty_state=empty_state,
        posts=metrics,
    )


@router.post("/posts/{published_post_id}/metrics", response_model=PostMetrics)
def record_metrics(
    published_post_id: int,
    payload: MetricsInput,
    db: Session = Depends(get_db),
    device: Device = Depends(get_current_device),
) -> PostMetrics:
    """Enter metrics read off LinkedIn.

    Manual entry exists because LinkedIn does not expose member post analytics
    to an ordinary integration. Unset fields stay NULL rather than becoming 0.
    """
    post = db.get(PublishedPost, published_post_id)
    if post is None:
        raise NotFoundError("That published post no longer exists.")

    snapshot = AnalyticsSnapshot(
        published_post_id=post.id,
        collected_at=utcnow(),
        source="manual",
        **payload.model_dump(),
    )
    db.add(snapshot)
    db.flush()
    compute_insights(db)
    db.commit()
    log_event(log, "ANALYTICS_RECORDED", published_post_id=post.id, device_id=device.id)
    return _post_metrics(db, post)


@router.post("/recompute", response_model=list[InsightOut])
def recompute(
    db: Session = Depends(get_db), _: Device = Depends(get_current_device)
) -> list[InsightOut]:
    insights = compute_insights(db)
    db.commit()
    return [InsightOut.model_validate(i) for i in insights]
