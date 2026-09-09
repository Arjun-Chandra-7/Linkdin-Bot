"""Networking copilot.

This module recommends people and drafts a note. It deliberately has **no**
capability to send a connection request, follow, message, like or comment, and
no code path that touches LinkedIn on the user's behalf. The final action is
always taken by the user, by hand, in LinkedIn's own app.

Candidates come from material the user already has - people who appear in the
sources they follow, or whom they add themselves - not from scraping LinkedIn.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import log_event
from app.core.settings_store import get_setting
from app.database.enums import ConnectionStatus, NotificationPriority, NotificationType
from app.database.models import ConnectionCandidate
from app.llm.factory import MeteredLLM
from app.notifications.service import notify

log = logging.getLogger(__name__)

MAX_NOTE_CHARS = 280  # LinkedIn's connection-note limit is 300; leave headroom.


@dataclass
class CandidateInput:
    name: str
    profile_url: str
    role: str | None = None
    company: str | None = None
    context: str = ""  # where the user encountered them
    shared_interests: list[str] | None = None


class ConnectionNote(BaseModel):
    reason: str = Field(description="Why this person is worth connecting with, specifically.")
    note: str = Field(description=f"A personal connection note under {MAX_NOTE_CHARS} characters.")
    shared_interests: list[str] = Field(default_factory=list)
    relevance: float = Field(default=0.5, description="0-1 relevance to the user's work.")


NOTE_SYSTEM = f"""You help a software engineer write a short, honest connection note.

Rules:
- Under {MAX_NOTE_CHARS} characters.
- Reference something specific and real about the person from the context given.
- Never invent a shared connection, a meeting that did not happen, or praise for \
work you were not told about.
- No flattery, no sales pitch, no "I'd love to pick your brain".
- Plain sentences. It should read like a person wrote it in ten seconds.
- If the context is too thin to say anything specific, write a short honest note \
that says why you are reaching out, rather than inventing detail."""


def fingerprint(profile_url: str, name: str) -> str:
    basis = profile_url.split("?")[0].rstrip("/").lower() or name.lower()
    return hashlib.sha256(basis.encode()).hexdigest()


def add_candidate(db: Session, candidate: CandidateInput) -> ConnectionCandidate | None:
    """Score a person and draft a note. Returns None if already known."""
    digest = fingerprint(candidate.profile_url, candidate.name)
    existing = db.execute(
        select(ConnectionCandidate).where(ConnectionCandidate.fingerprint == digest)
    ).scalar_one_or_none()
    if existing is not None:
        return None

    prompt = (
        f"PERSON: {candidate.name}\n"
        f"ROLE: {candidate.role or 'unknown'}\n"
        f"COMPANY: {candidate.company or 'unknown'}\n"
        f"CONTEXT (where they came up):\n{candidate.context or 'No additional context.'}\n\n"
        "Write the reason this person is relevant and a short connection note."
    )
    llm = MeteredLLM(db)
    output = llm.structured(
        prompt, ConnectionNote, task="connection_note", system=NOTE_SYSTEM, max_tokens=600
    )

    record = ConnectionCandidate(
        name=candidate.name[:200],
        role=(candidate.role or None),
        company=(candidate.company or None),
        profile_url=candidate.profile_url[:1000],
        reason_for_recommendation=output.reason
        or candidate.context[:500]
        or "Relevant to your work.",
        relevance_score=max(0.0, min(1.0, output.relevance)),
        shared_interests=(candidate.shared_interests or output.shared_interests)[:8],
        suggested_note=(output.note or "")[:MAX_NOTE_CHARS],
        status=ConnectionStatus.NEW,
        evidence=[{"context": candidate.context[:500]}] if candidate.context else [],
        fingerprint=digest,
    )
    db.add(record)
    db.flush()
    log_event(
        log,
        "CONNECTION_RECOMMENDED",
        candidate_id=record.id,
        relevance=round(record.relevance_score, 2),
    )
    return record


def notify_new_candidates(db: Session, candidates: list[ConnectionCandidate]) -> None:
    """One batched notification, never one per person."""
    high_value = [c for c in candidates if c.relevance_score >= 0.7]
    if not high_value:
        return
    top = max(high_value, key=lambda c: c.relevance_score)
    notify(
        db,
        type=NotificationType.NETWORK_CANDIDATE,
        title=(
            f"{len(high_value)} people worth connecting with"
            if len(high_value) > 1
            else "Someone worth connecting with"
        ),
        body=f"{top.name}" + (f" - {top.role}" if top.role else ""),
        priority=NotificationPriority.LOW,
        payload={"candidate_ids": [c.id for c in high_value]},
        dedupe_key=f"network:{min(c.id for c in high_value)}:{len(high_value)}",
    )


def recommendation_limit(db: Session) -> int:
    """Small by design - quality over quantity, and no mass activity."""
    return int(get_setting(db, "network_recommendations_per_run"))


# --------------------------------------------------------------------------
# Candidate discovery
# --------------------------------------------------------------------------

# Author bylines and mentions in the feeds the user already follows. This is
# the only automated discovery path, and it deliberately reads *public feed
# content the user has chosen to follow* - it never searches or scrapes
# LinkedIn, and it produces a handful of names, not a list.
_LINKEDIN_PROFILE = re.compile(r"https?://(?:[\w-]+\.)?linkedin\.com/in/[\w%-]+/?")


def extract_candidates_from_text(
    text: str, *, context: str = "", limit: int = 5
) -> list[CandidateInput]:
    """Find LinkedIn profile links that appear in content the user follows.

    Returns the raw candidates; scoring and note-drafting happen in
    ``add_candidate``, and the user still sends every invitation by hand.
    """
    found: list[CandidateInput] = []
    seen: set[str] = set()
    for match in _LINKEDIN_PROFILE.finditer(text or ""):
        url = match.group(0).rstrip("/")
        if url.lower() in seen:
            continue
        seen.add(url.lower())
        slug = url.rsplit("/", 1)[-1].replace("-", " ").strip()
        # Trailing id fragments in profile slugs are noise, not a surname.
        name = " ".join(
            part.capitalize() for part in slug.split() if not part.isdigit() and len(part) > 1
        )
        found.append(
            CandidateInput(
                name=name or slug,
                profile_url=url,
                context=context[:1500],
            )
        )
        if len(found) >= limit:
            break
    return found
