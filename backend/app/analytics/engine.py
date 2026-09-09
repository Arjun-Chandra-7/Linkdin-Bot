"""Learning engine.

Finds what actually works for *this* account, and is deliberately conservative
about saying so. Every insight carries its sample size and a confidence label,
and a segment with three posts is reported as EARLY_SIGNAL, never as fact.

Nothing here fabricates a metric: posts with no collected data are excluded
from the maths rather than treated as zeros.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import log_event
from app.database.base import utcnow
from app.database.enums import ConfidenceLevel
from app.database.models import AnalyticsSnapshot, LearningInsight, PublishedPost

log = logging.getLogger(__name__)

# Sample sizes below which a difference means nothing.
MIN_SEGMENT = 3
MIN_BASELINE = 4
# A segment must differ from baseline by this much to be worth reporting.
MIN_LIFT = 0.15


@dataclass
class Observation:
    post: PublishedPost
    engagement: float


def engagement_of(snapshot: AnalyticsSnapshot) -> float | None:
    """Weighted engagement, normalised by reach when reach is known.

    Returns ``None`` when nothing was ever collected - an absent metric is not
    a zero.
    """
    parts = [snapshot.reactions, snapshot.comments, snapshot.reposts, snapshot.clicks]
    if all(part is None for part in parts) and snapshot.impressions is None:
        return None
    weighted = (
        (snapshot.reactions or 0)
        + (snapshot.comments or 0) * 3.0
        + (snapshot.reposts or 0) * 5.0
        + (snapshot.clicks or 0) * 0.5
    )
    if snapshot.impressions:
        # Engagement rate per 1000 impressions keeps posts comparable.
        return (weighted / snapshot.impressions) * 1000.0
    return weighted


def latest_snapshot(db: Session, published_post_id: int) -> AnalyticsSnapshot | None:
    return db.execute(
        select(AnalyticsSnapshot)
        .where(AnalyticsSnapshot.published_post_id == published_post_id)
        .order_by(AnalyticsSnapshot.collected_at.desc())
        .limit(1)
    ).scalars().first()


def gather_observations(db: Session) -> list[Observation]:
    posts = db.execute(select(PublishedPost)).scalars().all()
    observations: list[Observation] = []
    for post in posts:
        snapshot = latest_snapshot(db, post.id)
        if snapshot is None:
            continue
        value = engagement_of(snapshot)
        if value is None:
            continue
        observations.append(Observation(post=post, engagement=value))
    return observations


def _confidence(sample_size: int, lift: float) -> ConfidenceLevel:
    if sample_size < MIN_SEGMENT:
        return ConfidenceLevel.INSUFFICIENT_DATA
    if sample_size < 6:
        return ConfidenceLevel.EARLY_SIGNAL
    if sample_size < 12:
        return ConfidenceLevel.MODERATE_CONFIDENCE
    return ConfidenceLevel.STRONG_SIGNAL if abs(lift) >= 0.25 else ConfidenceLevel.MODERATE_CONFIDENCE


def _length_bucket(char_count: int) -> str:
    if char_count < 600:
        return "under 600 chars"
    if char_count < 1000:
        return "600-1000 chars"
    if char_count < 1500:
        return "1000-1500 chars"
    return "over 1500 chars"


_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_PHRASING = {
    "post_type": "{segment} posts",
    "hook_type": "{segment} openings",
    "weekday": "Posts published on {segment}",
    "length": "Posts of {segment}",
    "category": "{segment} content",
}


def compute_insights(db: Session) -> list[LearningInsight]:
    """Recompute insights from scratch and persist them."""
    observations = gather_observations(db)
    now = utcnow()

    # Wipe previous insights: they are a derived view, not history.
    for stale in db.execute(select(LearningInsight)).scalars().all():
        db.delete(stale)
    db.flush()

    if len(observations) < MIN_BASELINE:
        insight = LearningInsight(
            dimension="overall",
            segment="all",
            statement=(
                f"Only {len(observations)} published post(s) have metrics so far. "
                f"At least {MIN_BASELINE} are needed before any pattern is meaningful."
            ),
            sample_size=len(observations),
            confidence=ConfidenceLevel.INSUFFICIENT_DATA,
            generated_at=now,
        )
        db.add(insight)
        db.flush()
        log_event(log, "LEARNING_INSUFFICIENT_DATA", observations=len(observations))
        return [insight]

    baseline = statistics.median(o.engagement for o in observations)
    if baseline <= 0:
        baseline = statistics.mean(o.engagement for o in observations) or 1.0

    dimensions: dict[str, callable] = {
        "post_type": lambda o: str(o.post.post_type),
        "category": lambda o: str(o.post.category),
        "hook_type": lambda o: o.post.hook_type or "UNKNOWN",
        "weekday": lambda o: _WEEKDAY_NAMES[o.post.weekday] if o.post.weekday is not None else None,
        "length": lambda o: _length_bucket(o.post.char_count or 0),
    }

    insights: list[LearningInsight] = []
    for dimension, key_fn in dimensions.items():
        groups: dict[str, list[float]] = {}
        for observation in observations:
            key = key_fn(observation)
            if key:
                groups.setdefault(key, []).append(observation.engagement)

        for segment, values in groups.items():
            if len(values) < MIN_SEGMENT:
                continue
            observed = statistics.median(values)
            lift = (observed - baseline) / baseline if baseline else 0.0
            if abs(lift) < MIN_LIFT:
                continue

            confidence = _confidence(len(values), lift)
            if confidence == ConfidenceLevel.INSUFFICIENT_DATA:
                continue

            direction = "outperform" if lift > 0 else "underperform"
            label = _PHRASING.get(dimension, "{segment}").format(segment=segment)
            hedge = {
                ConfidenceLevel.EARLY_SIGNAL: "Early signal only",
                ConfidenceLevel.MODERATE_CONFIDENCE: "Moderate confidence",
                ConfidenceLevel.STRONG_SIGNAL: "Consistent pattern",
            }[confidence]

            insights.append(
                LearningInsight(
                    dimension=dimension,
                    segment=segment,
                    statement=(
                        f"{label} {direction} the baseline by {abs(lift):.0%} "
                        f"({len(values)} post(s)). {hedge}."
                    ),
                    sample_size=len(values),
                    baseline=round(baseline, 3),
                    observed=round(observed, 3),
                    lift=round(lift, 3),
                    confidence=confidence,
                    generated_at=now,
                )
            )

    insights.sort(key=lambda i: (-abs(i.lift or 0), -i.sample_size))
    for insight in insights:
        db.add(insight)
    db.flush()
    log_event(
        log, "LEARNING_REPORT_GENERATED", insights=len(insights), observations=len(observations)
    )
    return insights


def predict_performance(db: Session, *, post_type: str, hook_type: str, char_count: int,
                        category: str, weekday: int | None = None) -> dict:
    """Estimate relative performance. Never presented as guaranteed reach."""
    insights = db.execute(select(LearningInsight)).scalars().all()
    if not insights or all(i.confidence == ConfidenceLevel.INSUFFICIENT_DATA for i in insights):
        return {
            "expected": "UNKNOWN",
            "confidence": ConfidenceLevel.INSUFFICIENT_DATA,
            "reasons": ["Not enough published posts with metrics to estimate performance yet."],
        }

    attributes = {
        "post_type": post_type,
        "hook_type": hook_type,
        "category": category,
        "length": _length_bucket(char_count),
    }
    if weekday is not None:
        attributes["weekday"] = _WEEKDAY_NAMES[weekday]

    reasons: list[str] = []
    total_lift = 0.0
    strongest = ConfidenceLevel.INSUFFICIENT_DATA
    order = [
        ConfidenceLevel.INSUFFICIENT_DATA,
        ConfidenceLevel.EARLY_SIGNAL,
        ConfidenceLevel.MODERATE_CONFIDENCE,
        ConfidenceLevel.STRONG_SIGNAL,
    ]

    for insight in insights:
        if attributes.get(insight.dimension) != insight.segment:
            continue
        lift = insight.lift or 0.0
        total_lift += lift
        sign = "+" if lift > 0 else "-"
        reasons.append(f"{sign} {insight.statement}")
        if order.index(ConfidenceLevel(insight.confidence)) > order.index(strongest):
            strongest = ConfidenceLevel(insight.confidence)

    if not reasons:
        return {
            "expected": "AT BASELINE",
            "confidence": ConfidenceLevel.INSUFFICIENT_DATA,
            "reasons": ["No learned pattern matches this post's format yet."],
        }

    if total_lift > 0.2:
        expected = "ABOVE BASELINE"
    elif total_lift < -0.2:
        expected = "BELOW BASELINE"
    else:
        expected = "AT BASELINE"

    return {
        "expected": expected,
        "confidence": strongest,
        "reasons": reasons[:6],
        "note": "Relative estimate from this account's own history - not a reach prediction.",
    }
