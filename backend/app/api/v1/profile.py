"""Profile positioning guidance.

Suggestions for the parts of a LinkedIn profile that a content strategy should
inform - headline, About, what to feature. It reads what the user has actually
published rather than asking them to fill in a form, and it never edits the
profile: LinkedIn has no API for that, and the text is theirs to place.
"""

from __future__ import annotations

import logging
from collections import Counter

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings_store import get_setting
from app.database.models import Device, PublishedPost
from app.database.session import get_db
from app.security.auth import get_current_device

log = logging.getLogger(__name__)
router = APIRouter(prefix="/profile", tags=["profile"])

MIN_POSTS_FOR_THEME = 3

THEME_WORDS: dict[str, tuple[str, ...]] = {
    "agents and tooling": ("agent", "agents", "tool", "tools", "orchestration", "mcp"),
    "AI engineering": ("llm", "model", "prompt", "inference", "embedding", "token"),
    "backend systems": ("queue", "scheduler", "database", "api", "job", "worker", "migration"),
    "mobile": ("android", "kotlin", "compose", "apk", "ios"),
    "reliability": ("idempoten", "retry", "backoff", "crash", "restart", "failure"),
}


class ProfileGuidance(BaseModel):
    posts_analysed: int
    dominant_theme: str | None = None
    cadence: str | None = None
    suggested_headline: str
    suggested_about: str
    recommendations: list[str] = []


def _theme(posts: list[PublishedPost]) -> str | None:
    if len(posts) < MIN_POSTS_FOR_THEME:
        return None
    corpus = " ".join(p.content.lower() for p in posts)
    scores = Counter()
    for theme, words in THEME_WORDS.items():
        scores[theme] = sum(corpus.count(word) for word in words)
    theme, score = scores.most_common(1)[0]
    return theme if score >= 3 else None


def _cadence(posts: list[PublishedPost]) -> str | None:
    if len(posts) < 2:
        return None
    ordered = sorted(posts, key=lambda p: p.published_at)
    span_days = (ordered[-1].published_at - ordered[0].published_at).days or 1
    per_week = len(posts) / (span_days / 7)
    if per_week >= 2.5:
        return "several a week"
    if per_week >= 0.8:
        return "about weekly"
    return "occasional"


@router.get("", response_model=ProfileGuidance)
def profile_guidance(
    db: Session = Depends(get_db), _: Device = Depends(get_current_device)
) -> ProfileGuidance:
    posts = db.execute(select(PublishedPost)).scalars().all()
    theme = _theme(posts)
    cadence = _cadence(posts)
    display_name = str(get_setting(db, "linkedin_display_name") or "").strip()
    current_headline = str(get_setting(db, "linkedin_headline") or "").strip()

    formats = Counter(str(p.post_type) for p in posts)
    build_logs = formats.get("BUILD_LOG", 0)

    if theme:
        headline = (
            f"{current_headline or 'Software engineer'} · building in public around {theme} · "
            f"writing up what actually breaks"
        )
    elif current_headline:
        headline = current_headline
    else:
        headline = (
            "Software engineer · building in public · writing up what I build and what breaks"
        )

    about_lines = [
        (f"I am {display_name}. " if display_name else "")
        + "I build things and write down what actually happened - including the parts that "
        "did not work.",
    ]
    if theme:
        about_lines.append(f"Most of my recent work has been around {theme}.")
    if posts:
        about_lines.append(
            f"I have published {len(posts)} post{'s' if len(posts) != 1 else ''} here so far, "
            f"{'mostly build logs' if build_logs >= len(posts) / 2 else 'across build logs and technical write-ups'}."
        )
    about_lines.append(
        "If you are working on something similar, I am happy to compare notes."
    )

    recommendations: list[str] = []
    if not posts:
        recommendations.append(
            "Publish a few posts before rewriting your profile - the guidance here gets "
            "sharper once there is something to read."
        )
    elif len(posts) < MIN_POSTS_FOR_THEME:
        recommendations.append(
            f"{len(posts)} published post{' is' if len(posts) == 1 else 's are'} too little "
            "history to infer a reliable profile theme."
        )
    if theme is None and posts:
        recommendations.append(
            "No single theme dominates yet. Pick the one you want to be known for and let "
            "the content mix lean that way in Settings."
        )
    if build_logs and build_logs == len(posts):
        recommendations.append(
            "Everything so far is a build log. One technical breakdown or opinion piece "
            "would widen who finds you."
        )
    if cadence == "occasional":
        recommendations.append(
            "Posting is irregular. A fixed slot or two a week is what makes a profile "
            "look active without becoming a feed."
        )
    recommendations.append(
        "Feature your two best posts on your profile - that section is the first thing a "
        "visitor reads after the headline."
    )

    return ProfileGuidance(
        posts_analysed=len(posts),
        dominant_theme=theme,
        cadence=cadence,
        suggested_headline=headline,
        suggested_about="\n\n".join(about_lines),
        recommendations=recommendations,
    )
