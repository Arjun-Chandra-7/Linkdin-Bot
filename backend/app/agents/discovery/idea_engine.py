"""Idea scoring.

Scoring runs *before* any expensive model call, so most candidates are
discarded for free. The ordering the system prefers is:

    actual experience > strong opinion > technical explanation > news summary

A news item with nothing personal attached scores badly on purpose - the
account is meant to be about what the user builds, not a feed reflector.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.discovery.sources import RawItem
from app.content.text import canonicalize, similarity
from app.core.logging import log_event
from app.database.enums import ContentCategory, IdeaStatus
from app.database.models import Idea, PublishedPost

log = logging.getLogger(__name__)

# Signals that an item is about the user's own work rather than the industry.
_PERSONAL_MARKERS = re.compile(
    r"\b(i|we|my|our|shipped|built|fixed|refactor\w*|migrat\w*|deploy\w*|released|"
    r"implemented|debugged|broke|rewrote|added|removed)\b",
    re.I,
)
_TECHNICAL_MARKERS = re.compile(
    r"\b(api|database|schema|query|cache|latency|queue|worker|token|embedding|agent|"
    r"scheduler|migration|index|async|retry|idempoten\w*|hash|auth|pipeline|model)\b",
    re.I,
)
# Marketing-flavoured items that rarely make good technical posts.
_LOW_VALUE = re.compile(
    r"\b(webinar|sponsored|discount|coupon|hiring|newsletter|roundup|top \d+|"
    r"best \d+ tools|listicle)\b",
    re.I,
)


def fingerprint(topic: str, url: str | None = None) -> str:
    basis = canonicalize(topic).lower()
    if url:
        basis += f"|{url.split('?')[0]}"
    return hashlib.sha256(basis.encode()).hexdigest()


def _timeliness(published_at: datetime | None) -> float:
    if published_at is None:
        return 0.5
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    age = datetime.now(UTC) - published_at
    if age < timedelta(days=2):
        return 1.0
    if age < timedelta(days=7):
        return 0.75
    if age < timedelta(days=30):
        return 0.45
    return 0.2


def score_item(
    item: RawItem, *, category_weight: float = 1.0, similar_to_published: float = 0.0
) -> dict[str, float]:
    """Cheap, deterministic scoring of one candidate."""
    text = f"{item.title}\n{item.summary}"
    words = len(text.split())

    personal_hits = len(_PERSONAL_MARKERS.findall(text))
    technical_hits = len({m.lower() for m in _TECHNICAL_MARKERS.findall(text)})

    personal_experience = min(1.0, personal_hits / 6.0)
    # Anything sourced from the user's own repo *is* personal experience.
    if item.category in {ContentCategory.BUILD_LOG, ContentCategory.MILESTONE}:
        personal_experience = max(personal_experience, 0.85)

    linkedin_fit = 0.75
    if words < 6:
        linkedin_fit -= 0.35
    if _LOW_VALUE.search(text):
        linkedin_fit -= 0.45
    linkedin_fit = max(0.0, min(1.0, linkedin_fit + min(technical_hits, 6) * 0.04))

    relevance = min(1.0, 0.35 + technical_hits * 0.09 + personal_experience * 0.35)
    originality = max(0.0, 1.0 - similar_to_published)
    timeliness = _timeliness(item.published_at)
    evidence = 0.85 if item.url else 0.5
    if item.summary and len(item.summary) > 120:
        evidence = min(1.0, evidence + 0.1)

    final = (
        relevance * 0.22
        + originality * 0.18
        + personal_experience * 0.26
        + linkedin_fit * 0.14
        + evidence * 0.10
        + timeliness * 0.10
    ) * category_weight

    return {
        "relevance_score": round(relevance, 3),
        "originality_score": round(originality, 3),
        "timeliness_score": round(timeliness, 3),
        "personal_experience_score": round(personal_experience, 3),
        "evidence_quality": round(evidence, 3),
        "linkedin_fit_score": round(linkedin_fit, 3),
        "final_score": round(min(final, 1.0), 3),
    }


def _similarity_to_published(db: Session, text: str, limit: int = 40) -> float:
    published = (
        db.execute(select(PublishedPost.content).order_by(PublishedPost.id.desc()).limit(limit))
        .scalars()
        .all()
    )
    return max((similarity(text, content) for content in published), default=0.0)


def normalize_mix(mix: dict[str, float] | None) -> dict[str, float]:
    """Turn the desired content mix into multipliers centred on 1.0.

    ``category_mix`` expresses the *proportion* of output wanted from each
    category (40% build logs, 20% AI observations, ...). Those fractions must
    not be multiplied into a score directly: they are all below 1, so doing so
    drags every idea down and, with a threshold of 0.55, rejects everything.

    Dividing by the mean turns them into relative preferences instead - a
    category you want more of scores above 1.0, one you want less of below.
    """
    if not mix:
        return {}
    values = [float(v) for v in mix.values() if float(v) > 0]
    if not values:
        return {}
    mean = sum(values) / len(values)
    if mean <= 0:
        return {}
    # Dampen the preference to roughly +/-30%. At full strength a 1.6x
    # multiplier pushes every build log past the 1.0 ceiling, so they all tie
    # and the ranking inside the category - the part that decides what gets
    # written - is lost. The mix should tilt the ordering, not flatten it.
    return {
        key: 1.0 + ((float(value) / mean) - 1.0) * 0.3
        for key, value in mix.items()
    }


def ingest_items(
    db: Session,
    items: list[RawItem],
    *,
    source_id: int | None = None,
    category_weights: dict[str, float] | None = None,
) -> list[Idea]:
    """Score candidates and store the new ones. Duplicates are skipped."""
    weights = normalize_mix(category_weights)
    created: list[Idea] = []

    for item in items:
        digest = fingerprint(item.title, item.url)
        existing = db.execute(
            select(Idea).where(Idea.fingerprint == digest)
        ).scalar_one_or_none()
        if existing is not None:
            continue

        text = f"{item.title}\n{item.summary}"
        scores = score_item(
            item,
            category_weight=float(weights.get(str(item.category), 1.0)),
            similar_to_published=_similarity_to_published(db, text),
        )

        idea = Idea(
            topic=item.title[:500],
            summary=item.summary[:2000] or None,
            source_id=source_id,
            source_ref=item.url,
            category=item.category,
            why_it_matters=None,
            status=IdeaStatus.SCORED,
            fingerprint=digest,
            published_at=item.published_at,
            extra=item.extra or {},
            **scores,
        )
        db.add(idea)
        created.append(idea)

    db.flush()
    if created:
        log_event(log, "IDEAS_INGESTED", count=len(created), source_id=source_id)
    return created


def select_promising(db: Session, *, threshold: float, limit: int) -> list[Idea]:
    """Highest-scoring unused ideas above the threshold."""
    return list(
        db.execute(
            select(Idea)
            .where(Idea.status == IdeaStatus.SCORED, Idea.final_score >= threshold)
            .order_by(Idea.final_score.desc(), Idea.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )


def reject_weak(db: Session, *, threshold: float) -> int:
    """Mark everything below the bar rejected so it is not reconsidered."""
    weak = (
        db.execute(
            select(Idea).where(Idea.status == IdeaStatus.SCORED, Idea.final_score < threshold)
        )
        .scalars()
        .all()
    )
    for idea in weak:
        idea.status = IdeaStatus.REJECTED
        idea.reject_reason = f"Scored {idea.final_score:.2f}, below threshold {threshold:.2f}"
    db.flush()
    return len(weak)
