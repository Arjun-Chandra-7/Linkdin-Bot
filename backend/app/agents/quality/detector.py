"""The quality gate / AI-slop detector.

A draft has to earn its way onto the user's phone. Scoring is deterministic
and free: it runs on every draft, is reproducible, and can be unit-tested.
An LLM second opinion is requested only for borderline drafts, which keeps
the cost of rejecting bad writing near zero.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field

from app.agents.quality.patterns import (
    ACRONYM,
    ANY_NUMBER,
    CLICHE_PHRASES,
    CONCRETE_NUMBER,
    EMOJI,
    ENGAGEMENT_BAIT,
    FIRST_PERSON,
    GENERIC_HASHTAGS,
    DURATION,
    HASHTAG,
    IDENTIFIER,
    PROPER_NOUN,
    SLOP_PATTERNS,
    SPELLED_NUMBER,
    TECHNICAL_TERMS,
)
from app.content.text import canonicalize

log = logging.getLogger(__name__)

APPROVE = "APPROVE"
REVIEW = "REVIEW"
REJECT = "REJECT"


@dataclass
class QualityReport:
    quality: int
    specificity: int
    originality: int
    personal_relevance: int
    technical_depth: int
    evidence: int
    readability: int
    repetition: int
    ai_slop_probability: float
    engagement_bait_probability: float
    claim_confidence: float
    recommendation: str
    issues: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def analyze(text: str, *, claim_confidence: float = 0.8) -> QualityReport:
    """Score a draft. Pure function - same text always scores the same."""
    body = canonicalize(text)
    lower = body.lower()
    words = body.split()
    word_count = max(len(words), 1)
    issues: list[str] = []
    notes: list[str] = []

    # ---- Slop signals -------------------------------------------------
    cliches = [phrase for phrase in CLICHE_PHRASES if phrase in lower]
    slop_hits = [label for pattern, label in SLOP_PATTERNS if re.search(pattern, lower, re.M)]
    bait_hits = [label for pattern, label in ENGAGEMENT_BAIT if re.search(pattern, lower, re.M)]

    emoji_count = len(EMOJI.findall(body))
    emoji_density = emoji_count / word_count
    hashtags = [h.strip().lower() for h in HASHTAG.findall(body)]
    generic_hashtags = [h for h in hashtags if h in GENERIC_HASHTAGS]

    paragraphs = _paragraphs(body)
    one_liners = [p for p in paragraphs if len(p.split()) <= 4]
    one_liner_ratio = len(one_liners) / max(len(paragraphs), 1)

    # ---- Substance signals --------------------------------------------
    first_person_hits = len(FIRST_PERSON.findall(body))
    concrete_numbers = len(CONCRETE_NUMBER.findall(body))
    any_numbers = len(ANY_NUMBER.findall(body))
    technical_hits = len(set(m.lower() for m in TECHNICAL_TERMS.findall(body)))

    # Structural specificity: named things the author is actually working with.
    acronyms = {a for a in ACRONYM.findall(body) if a not in {"I", "A"}}
    identifiers = set(IDENTIFIER.findall(body))
    proper_nouns = set(PROPER_NOUN.findall(body))
    spelled_numbers = len(SPELLED_NUMBER.findall(body))
    durations = len(DURATION.findall(body))
    # Anything that pins the post to a specific situation rather than a general one.
    concrete_details = (
        concrete_numbers * 2
        + len(acronyms)
        + len(identifiers)
        + min(len(proper_nouns), 6)
        + spelled_numbers
        + min(durations, 3)
    )
    named_things = len(acronyms) + len(identifiers)

    sentences = _sentences(body)
    avg_sentence_words = word_count / max(len(sentences), 1)

    # Repeated sentence openings read as template-generated.
    openings = [" ".join(s.split()[:2]).lower() for s in sentences if s.split()]
    repeated_openings = len(openings) - len(set(openings))

    # ---- Component scores ---------------------------------------------
    specificity = _clamp(
        28
        + concrete_numbers * 12
        + min(any_numbers, 6) * 3
        + min(technical_hits, 10) * 3.0
        + min(concrete_details, 14) * 3.2
    )
    technical_depth = _clamp(18 + min(technical_hits, 14) * 5 + min(named_things, 8) * 4.5)
    personal_relevance = _clamp(18 + min(first_person_hits, 8) * 11)
    evidence = _clamp(
        22 + concrete_numbers * 15 + min(technical_hits, 8) * 4 + min(concrete_details, 12) * 3.5
    )

    originality = _clamp(
        92 - len(cliches) * 16 - len(slop_hits) * 18 - len(generic_hashtags) * 5
    )

    # Readability peaks around 12-22 words per sentence.
    if avg_sentence_words < 5:
        readability = 55.0
    elif avg_sentence_words <= 22:
        readability = 90.0
    elif avg_sentence_words <= 30:
        readability = 72.0
    else:
        readability = 50.0
    if word_count < 40:
        readability -= 15
        notes.append("Very short for a LinkedIn post.")

    repetition = _clamp(95 - repeated_openings * 12)

    # ---- Probabilities -------------------------------------------------
    slop = 0.03
    slop += min(len(cliches), 4) * 0.13
    slop += min(len(slop_hits), 4) * 0.16
    slop += 0.20 if one_liner_ratio > 0.55 and len(paragraphs) >= 4 else 0.0
    slop += 0.15 if emoji_density > 0.035 else (0.06 if emoji_density > 0.015 else 0.0)
    slop += 0.10 if len(generic_hashtags) >= 3 else 0.0
    slop -= 0.12 if concrete_numbers >= 2 else 0.0
    slop -= 0.10 if first_person_hits >= 4 else 0.0
    slop -= 0.08 if technical_hits >= 6 else 0.0
    ai_slop_probability = round(min(max(slop, 0.0), 0.99), 3)

    bait_probability = round(min(len(bait_hits) * 0.3 + len(generic_hashtags) * 0.05, 0.99), 3)

    # ---- Issues the user would actually care about ---------------------
    for phrase in cliches[:4]:
        issues.append(f"Cliché phrase: '{phrase}'")
    for label in slop_hits[:4]:
        issues.append(f"AI writing pattern: {label}")
    for label in bait_hits[:3]:
        issues.append(f"Engagement bait: {label}")
    if emoji_density > 0.035:
        issues.append(f"Heavy emoji use ({emoji_count} in {word_count} words)")
    if one_liner_ratio > 0.55 and len(paragraphs) >= 4:
        issues.append("Mostly one-line paragraphs - reads as manufactured suspense")
    if generic_hashtags:
        issues.append(f"Generic hashtags: {', '.join(generic_hashtags[:4])}")
    if concrete_numbers == 0 and technical_hits < 3 and concrete_details < 4:
        issues.append("No concrete details - nothing specific to the author's work")
    if repeated_openings >= 3:
        issues.append("Several sentences start the same way")

    # ---- Overall -------------------------------------------------------
    quality = (
        specificity * 0.22
        + originality * 0.24
        + personal_relevance * 0.14
        + technical_depth * 0.14
        + evidence * 0.10
        + readability * 0.10
        + repetition * 0.06
    )
    quality *= 1.0 - (ai_slop_probability * 0.45)
    quality *= 1.0 - (bait_probability * 0.25)
    quality *= 0.75 + 0.25 * max(0.0, min(claim_confidence, 1.0))
    quality_score = int(round(_clamp(quality)))

    if ai_slop_probability >= 0.6 or quality_score < 45 or bait_probability >= 0.6:
        recommendation = REJECT
    elif ai_slop_probability >= 0.3 or quality_score < 68:
        recommendation = REVIEW
    else:
        recommendation = APPROVE

    return QualityReport(
        quality=quality_score,
        specificity=int(specificity),
        originality=int(originality),
        personal_relevance=int(personal_relevance),
        technical_depth=int(technical_depth),
        evidence=int(evidence),
        readability=int(readability),
        repetition=int(repetition),
        ai_slop_probability=ai_slop_probability,
        engagement_bait_probability=bait_probability,
        claim_confidence=round(claim_confidence, 3),
        recommendation=recommendation,
        issues=issues,
        notes=notes,
    )


def passes_gate(report: QualityReport, *, min_quality: int, max_slop: float) -> bool:
    """Hard gate applied before a draft is ever sent to the phone."""
    return (
        report.recommendation != REJECT
        and report.quality >= min_quality
        and report.ai_slop_probability <= max_slop
    )
