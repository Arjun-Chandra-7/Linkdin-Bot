"""Personal style memory.

The strongest training signal is not what the user says they like - it is what
they keep, what they rewrite, what they delete and what they reject. This
module turns the accumulated StyleFeedback rows into a handful of concrete
notes the writer prompt can act on.

Everything here is sample-size aware: with three data points it says nothing.
"""

from __future__ import annotations

import logging
import re
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import PublishedPost, StyleFeedback

log = logging.getLogger(__name__)

MIN_SIGNALS = 4  # below this, preferences are noise
_WORD = re.compile(r"[a-z][a-z'-]+")


def _phrase_tokens(phrases: list[str]) -> list[str]:
    tokens: list[str] = []
    for phrase in phrases:
        tokens.extend(_WORD.findall(phrase.lower()))
    return tokens


def learn_style_notes(db: Session, limit: int = 200) -> list[str]:
    """Concrete, prompt-ready notes. Empty until there is enough evidence."""
    feedback = (
        db.execute(select(StyleFeedback).order_by(StyleFeedback.id.desc()).limit(limit))
        .scalars()
        .all()
    )
    if len(feedback) < MIN_SIGNALS:
        return []

    notes: list[str] = []

    # 1. Phrases the user repeatedly deletes when editing.
    removed = Counter()
    for row in feedback:
        if row.kind == "edit":
            for phrase in row.removed_phrases or []:
                cleaned = phrase.strip()
                if 8 <= len(cleaned) <= 90:
                    removed[cleaned.lower()] += 1
    repeat_removals = [phrase for phrase, count in removed.most_common(6) if count >= 2]
    if repeat_removals:
        notes.append(
            "This author consistently deletes lines like: "
            + "; ".join(f'"{p}"' for p in repeat_removals[:3])
        )

    # 2. Words that show up disproportionately in deletions.
    removed_tokens = Counter(
        _phrase_tokens(
            [p for row in feedback if row.kind == "edit" for p in row.removed_phrases or []]
        )
    )
    kept_tokens = Counter(
        _phrase_tokens(
            [p for row in feedback if row.kind == "edit" for p in row.added_phrases or []]
        )
    )
    disliked = [
        word
        for word, count in removed_tokens.most_common(40)
        if count >= 3 and count > kept_tokens.get(word, 0) * 2 and len(word) > 4
    ]
    if disliked:
        notes.append("Avoid these words - the author strips them out: " + ", ".join(disliked[:8]))

    # 3. Length preference, derived from how edits change length.
    deltas = [row.length_delta for row in feedback if row.kind == "edit" and row.length_delta]
    if len(deltas) >= MIN_SIGNALS:
        average = sum(deltas) / len(deltas)
        if average < -120:
            notes.append("The author usually shortens drafts - aim tighter than feels natural.")
        elif average > 120:
            notes.append("The author usually expands drafts - go one level deeper on detail.")

    # 4. Rejection reasons, which say what to stop doing.
    reasons = Counter(row.reason for row in feedback if row.kind == "reject" and row.reason)
    for reason, count in reasons.most_common(3):
        if count >= 2:
            notes.append(
                {
                    "TOO_GENERIC": "Past drafts were rejected as too generic - lead with a specific detail.",
                    "SOUNDS_AI_GENERATED": "Past drafts were rejected for sounding AI-written - vary rhythm, cut symmetry.",
                    "BAD_HOOK": "Past drafts were rejected for weak first lines - open with a concrete fact.",
                    "TOO_LONG": "Past drafts were rejected as too long - be noticeably shorter.",
                    "TOO_CRINGE": "Past drafts were rejected as cringe - no motivational or performative tone.",
                    "NOT_INTERESTING": "Past drafts were rejected as uninteresting - lead with the surprising part.",
                }.get(reason, f"Past drafts were rejected for: {reason}.")
            )

    # 5. Length of what actually got published.
    published_lengths = (
        db.execute(select(PublishedPost.char_count).order_by(PublishedPost.id.desc()).limit(20))
        .scalars()
        .all()
    )
    if len(published_lengths) >= MIN_SIGNALS:
        average_length = sum(published_lengths) / len(published_lengths)
        notes.append(f"Published posts average about {int(average_length)} characters.")

    return notes[:6]


def preferred_length_range(db: Session, default: tuple[int, int]) -> tuple[int, int]:
    """Length band from published history, falling back to configuration."""
    lengths = (
        db.execute(select(PublishedPost.char_count).order_by(PublishedPost.id.desc()).limit(20))
        .scalars()
        .all()
    )
    lengths = [length for length in lengths if length]
    if len(lengths) < MIN_SIGNALS:
        return default
    lengths.sort()
    low = lengths[len(lengths) // 4]
    high = lengths[(3 * len(lengths)) // 4]
    if high - low < 300:
        high = low + 300
    return int(low), int(high)
