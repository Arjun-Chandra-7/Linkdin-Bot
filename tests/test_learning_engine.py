"""The learning engine and performance prediction.

The property that matters most here is restraint: it must not claim a pattern
it cannot support, and it must never treat an uncollected metric as a zero.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.analytics.engine import compute_insights, engagement_of, predict_performance
from app.approvals.service import add_version
from app.database.base import utcnow
from app.database.enums import (
    ConfidenceLevel,
    ContentCategory,
    DraftStatus,
    PostType,
    PublishMethod,
)
from app.database.models import AnalyticsSnapshot, Approval, Draft, PublishedPost


@pytest.fixture()
def publish_history(db):
    """Create published posts with metrics, respecting real foreign keys."""

    def _create(rows: list[tuple[PostType, str, int, int | None]]):
        created = []
        for index, (post_type, hook, chars, reactions) in enumerate(rows):
            draft = Draft(
                title=f"Post {index}",
                post_type=post_type,
                category=(
                    ContentCategory.BUILD_LOG
                    if post_type == PostType.BUILD_LOG
                    else ContentCategory.AI_OBSERVATION
                ),
                status=DraftStatus.PUBLISHED,
            )
            db.add(draft)
            db.flush()
            version = add_version(db, draft, "x " * (chars // 2))
            approval = Approval(
                draft_id=draft.id,
                version_id=version.id,
                action="APPROVE",
                approved_content_hash=version.content_hash,
                approval_timestamp=utcnow(),
                device_id="dev-1",
            )
            db.add(approval)
            db.flush()

            post = PublishedPost(
                draft_id=draft.id,
                version_id=version.id,
                approval_id=approval.id,
                content=version.content,
                content_hash=version.content_hash,
                published_at=utcnow() - timedelta(days=30 - index),
                method=PublishMethod.MANUAL,
                post_type=post_type,
                category=draft.category,
                char_count=chars,
                hook_type=hook,
                weekday=index % 5,
                hour_local=10,
            )
            db.add(post)
            db.flush()

            if reactions is not None:
                db.add(
                    AnalyticsSnapshot(
                        published_post_id=post.id,
                        collected_at=utcnow(),
                        source="manual",
                        impressions=1000,
                        reactions=reactions,
                        comments=reactions // 6,
                    )
                )
            created.append(post)
        db.commit()
        return created

    return _create


STRONG_HISTORY = [
    (PostType.BUILD_LOG, "FAILURE", 900, 55),
    (PostType.BUILD_LOG, "FAILURE", 950, 62),
    (PostType.BUILD_LOG, "PERSONAL", 880, 48),
    (PostType.BUILD_LOG, "FAILURE", 1000, 58),
    (PostType.NEWS_WITH_ANALYSIS, "STATEMENT", 700, 18),
    (PostType.NEWS_WITH_ANALYSIS, "QUESTION", 650, 15),
    (PostType.NEWS_WITH_ANALYSIS, "STATEMENT", 720, 21),
    (PostType.TECHNICAL_BREAKDOWN, "STATEMENT", 1200, 33),
    (PostType.TECHNICAL_BREAKDOWN, "NUMBER", 1150, 37),
    (PostType.TECHNICAL_BREAKDOWN, "STATEMENT", 1300, 30),
]


def test_says_nothing_without_enough_data(db, publish_history):
    publish_history(STRONG_HISTORY[:2])
    insights = compute_insights(db)

    assert len(insights) == 1
    assert insights[0].confidence == ConfidenceLevel.INSUFFICIENT_DATA
    assert "at least" in insights[0].statement.lower()


def test_finds_real_patterns_once_there_is_history(db, publish_history):
    publish_history(STRONG_HISTORY)
    insights = compute_insights(db)

    assert len(insights) > 1
    by_dimension = {i.dimension for i in insights}
    assert "post_type" in by_dimension

    build_log = next(
        i for i in insights if i.dimension == "post_type" and i.segment == "BUILD_LOG"
    )
    news = next(
        (i for i in insights if i.dimension == "post_type" and i.segment == "NEWS_WITH_ANALYSIS"),
        None,
    )
    assert build_log.lift > 0, "build logs clearly outperformed in this data"
    if news is not None:
        assert news.lift < 0

    # Every insight must carry its sample size and a hedge.
    for insight in insights:
        assert insight.sample_size >= 3
        assert insight.confidence in {
            ConfidenceLevel.EARLY_SIGNAL,
            ConfidenceLevel.MODERATE_CONFIDENCE,
            ConfidenceLevel.STRONG_SIGNAL,
        }
        assert str(insight.sample_size) in insight.statement


def test_small_samples_are_labelled_early_signal_not_fact(db, publish_history):
    """With a handful of posts the engine either stays quiet or hedges.

    Six posts is not enough for a confident claim, so a small difference is
    reported as nothing at all rather than as a finding - and anything that
    does clear the bar is labelled an early signal, never a fact.
    """
    publish_history(STRONG_HISTORY[:6])
    insights = [i for i in compute_insights(db) if i.dimension == "post_type"]

    for insight in insights:
        assert insight.confidence in {
            ConfidenceLevel.EARLY_SIGNAL,
            ConfidenceLevel.MODERATE_CONFIDENCE,
        }
        assert insight.confidence != ConfidenceLevel.STRONG_SIGNAL
        if insight.confidence == ConfidenceLevel.EARLY_SIGNAL:
            assert "early signal" in insight.statement.lower()


def test_a_difference_too_small_to_matter_is_not_reported(db, publish_history):
    """Near-identical performance must not be dressed up as a pattern."""
    flat = [(PostType.BUILD_LOG, "FAILURE", 900, 40) for _ in range(4)] + [
        (PostType.NEWS_WITH_ANALYSIS, "STATEMENT", 900, 39) for _ in range(4)
    ]
    publish_history(flat)
    insights = [i for i in compute_insights(db) if i.dimension == "post_type"]
    assert insights == [], "a 2% difference is noise, not a finding"


def test_posts_without_metrics_are_excluded_not_counted_as_zero(db, publish_history):
    """A post with no data must not drag the average down."""
    publish_history(STRONG_HISTORY[:4] + [(PostType.BUILD_LOG, "FAILURE", 900, None)])
    insights = compute_insights(db)

    build_log = [i for i in insights if i.segment == "BUILD_LOG" and i.dimension == "post_type"]
    for insight in build_log:
        assert insight.sample_size == 4, "the post with no metrics should be excluded"


def test_engagement_of_distinguishes_missing_from_zero():
    nothing_collected = AnalyticsSnapshot(published_post_id=1, source="manual")
    assert engagement_of(nothing_collected) is None

    genuinely_zero = AnalyticsSnapshot(
        published_post_id=1, source="manual", impressions=500, reactions=0
    )
    assert engagement_of(genuinely_zero) == 0.0


def test_prediction_is_unknown_without_history(db):
    prediction = predict_performance(
        db, post_type="BUILD_LOG", hook_type="FAILURE", char_count=900, category="BUILD_LOG"
    )
    assert prediction["expected"] == "UNKNOWN"
    assert prediction["confidence"] == ConfidenceLevel.INSUFFICIENT_DATA


def test_prediction_uses_learned_patterns_and_never_promises_reach(db, publish_history):
    publish_history(STRONG_HISTORY)
    compute_insights(db)

    strong = predict_performance(
        db, post_type="BUILD_LOG", hook_type="FAILURE", char_count=920, category="BUILD_LOG"
    )
    weak = predict_performance(
        db,
        post_type="NEWS_WITH_ANALYSIS",
        hook_type="QUESTION",
        char_count=700,
        category="AI_OBSERVATION",
    )

    assert strong["expected"] == "ABOVE BASELINE"
    assert weak["expected"] in {"BELOW BASELINE", "AT BASELINE"}
    assert strong["reasons"]
    # It must be framed as relative, never as a reach guarantee.
    assert "not a reach prediction" in strong.get("note", "").lower()
    for text in (*strong["reasons"], strong.get("note", "")):
        assert "guarantee" not in text.lower()
