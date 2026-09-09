"""Idea scoring: the cheap filter that decides what is worth spending on."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.agents.discovery.idea_engine import (
    ingest_items,
    normalize_mix,
    reject_weak,
    score_item,
    select_promising,
)
from app.agents.discovery.sources import RawItem, strip_commit_prefix
from app.core.settings_store import DEFAULTS
from app.database.enums import ContentCategory, IdeaStatus

DEFAULT_THRESHOLD = DEFAULTS["idea_score_threshold"]


def _item(title: str, summary: str = "", category=ContentCategory.AI_OBSERVATION, **kwargs):
    return RawItem(title=title, summary=summary, category=category, **kwargs)


def test_scoring_prefers_experience_over_news():
    """actual experience > strong opinion > explanation > news summary."""
    own_work = score_item(
        _item(
            "requeue orphaned RUNNING jobs after a crash",
            "The scheduler lost jobs when the laptop slept. Added idempotency keys and WAL.",
            ContentCategory.BUILD_LOG,
            published_at=datetime.now(UTC),
        )
    )
    substantive_news = score_item(
        _item(
            "New paper measures retrieval degradation past 100k tokens",
            "Researchers benchmarked recall across context lengths with reproducible code.",
            published_at=datetime.now(UTC),
            url="https://example.com/paper",
        )
    )
    listicle = score_item(
        _item(
            "Top 10 AI tools you need in 2026",
            "A roundup of the best AI tools.",
            published_at=datetime.now(UTC),
        )
    )

    assert own_work["final_score"] > substantive_news["final_score"] > listicle["final_score"]
    assert listicle["final_score"] < DEFAULT_THRESHOLD, "marketing listicles must be filtered out"
    assert own_work["final_score"] > DEFAULT_THRESHOLD


def test_content_mix_tilts_ranking_without_rejecting_everything():
    """Regression: the mix fractions must not be multiplied into scores.

    ``category_mix`` states the desired *proportion* of output per category.
    Every fraction is below 1, so using them directly as multipliers dragged
    every idea under the threshold and the system produced no drafts at all.
    """
    weights = normalize_mix(DEFAULTS["category_mix"])

    assert weights["BUILD_LOG"] > 1.0, "the preferred category should rank higher"
    assert weights["MILESTONE"] < 1.0, "a less-wanted category should rank lower"
    # Nothing may be scaled so hard that a good idea drops under the bar.
    assert all(0.7 <= w <= 1.4 for w in weights.values()), weights


def test_mix_weighting_keeps_good_build_logs_above_the_threshold(db):
    items = [
        _item(
            "add idempotency keys to the publish job",
            "A redelivered job published twice. Keyed off the content hash instead of the row id.",
            ContentCategory.BUILD_LOG,
            published_at=datetime.now(UTC),
            url="https://github.com/x/y/commit/abc",
        )
    ]
    created = ingest_items(db, items, category_weights=DEFAULTS["category_mix"])
    db.commit()

    assert len(created) == 1
    assert created[0].final_score >= DEFAULT_THRESHOLD, (
        f"a real build log scored {created[0].final_score}, below the "
        f"{DEFAULT_THRESHOLD} threshold - the pipeline would produce nothing"
    )


def test_scores_keep_resolution_for_ranking(db):
    """If everything saturates at 1.0 the ordering carries no information."""
    items = [
        _item(
            f"fix the {name} path",
            f"Details about {name} and how the {name} broke.",
            ContentCategory.BUILD_LOG,
            published_at=datetime.now(UTC),
        )
        for name in ("scheduler", "queue", "cache", "index", "token")
    ] + [
        _item(f"thoughts on {name}", "", ContentCategory.AI_OBSERVATION)
        for name in ("agents", "context", "evals")
    ]
    ingest_items(db, items, category_weights=DEFAULTS["category_mix"])
    db.commit()

    from app.database.models import Idea

    values = {round(i.final_score, 3) for i in db.query(Idea).all()}
    assert len(values) > 1, "all ideas tied - ranking would be arbitrary"


def test_duplicate_items_are_not_ingested_twice(db):
    item = _item(
        "add WAL mode to sqlite",
        "It stopped the writer blocking readers.",
        ContentCategory.BUILD_LOG,
        url="https://example.com/1",
    )
    assert len(ingest_items(db, [item])) == 1
    db.commit()
    assert ingest_items(db, [item]) == []
    db.commit()


def test_weak_ideas_are_rejected_before_any_model_call(db):
    ingest_items(
        db,
        [
            _item("Top 10 AI tools you need in 2026", "roundup"),
            _item(
                "add retry backoff to the publish job",
                "Jobs failed forever without backoff; capped at an hour.",
                ContentCategory.BUILD_LOG,
                published_at=datetime.now(UTC),
            ),
        ],
        category_weights=DEFAULTS["category_mix"],
    )
    db.commit()

    rejected = reject_weak(db, threshold=DEFAULT_THRESHOLD)
    promising = select_promising(db, threshold=DEFAULT_THRESHOLD, limit=5)

    assert rejected >= 1
    assert len(promising) >= 1
    assert all(i.status == IdeaStatus.SCORED for i in promising)


def test_stale_items_score_lower_than_fresh_ones():
    fresh = score_item(_item("model release notes", "details", published_at=datetime.now(UTC)))
    stale = score_item(
        _item(
            "model release notes", "details", published_at=datetime.now(UTC) - timedelta(days=200)
        )
    )
    assert fresh["timeliness_score"] > stale["timeliness_score"]


def test_commit_prefixes_are_stripped_from_topics():
    assert strip_commit_prefix("feat: add approval core") == "add approval core"
    assert strip_commit_prefix("fix(api): handle stale hash") == "handle stale hash"
    assert strip_commit_prefix("a normal sentence") == "a normal sentence"
