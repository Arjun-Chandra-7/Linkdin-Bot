"""Deterministic offline provider.

This is not a stub that returns lorem ipsum. It builds its output from the
actual prompt so the full pipeline - scoring, drafting, quality gating,
approval, scheduling - can be exercised end to end, in tests and in a live
demo, with no API key and no spend. Output is seeded by the prompt, so the
same input always produces the same draft.
"""

from __future__ import annotations

import hashlib
import random
import re
from typing import Any, TypeVar, get_args, get_origin

from pydantic import BaseModel

from app.llm.base import LLMProvider, LLMResponse, ProviderStatus

T = TypeVar("T", bound=BaseModel)

_TOPIC_RE = re.compile(r"TOPIC:\s*(.+)", re.I)
# Section labels carry qualifiers ("NOTES FROM THE AUTHOR (first-hand):"), so
# match up to the colon rather than requiring a bare keyword.
_NOTES_RE = re.compile(
    r"(?:NOTES|EVIDENCE|RESEARCH)[^:\n]*:\s*(.+?)(?=\n[A-Z][A-Z ]{2,}[^:\n]*:|\Z)",
    re.I | re.S,
)


def _seed_for(text: str) -> int:
    return int(hashlib.blake2b(text.encode(), digest_size=8).hexdigest(), 16)


def _extract_topic(prompt: str) -> str:
    match = _TOPIC_RE.search(prompt)
    if match:
        return match.group(1).strip().rstrip(".")
    first = next((line.strip() for line in prompt.splitlines() if line.strip()), "a recent change")
    return first[:120]


def _extract_notes(prompt: str) -> list[str]:
    match = _NOTES_RE.search(prompt)
    if not match:
        return []
    raw = match.group(1)
    lines = [line.strip(" -*\t") for line in raw.splitlines() if len(line.strip(" -*\t")) > 12]
    if len(lines) == 1:
        # Prose notes: split into sentences so they read as distinct points.
        lines = [s.strip() for s in re.split(r"(?<=[.!?])\s+", lines[0]) if len(s.strip()) > 12]
    return lines[:4]


def _build_post(prompt: str, rng: random.Random) -> str:
    """Compose a plausible build-log style post about the actual topic."""
    topic = _extract_topic(prompt)
    notes = _extract_notes(prompt)
    lower = prompt.lower()

    # Headline-style hooks, because a topic may be a noun phrase ("the job
    # queue") or an imperative lifted from a commit subject ("add retries").
    # A colon reads correctly with both; "I spent this week on add retries"
    # does not.
    if "failure" in lower or "broke" in lower:
        hook = f"Something broke this week: {topic}."
    elif "milestone" in lower:
        hook = f"Milestone reached: {topic}."
    elif "opinion" in lower or "news" in lower:
        hook = f"A note on {topic}, from actually using it."
    else:
        hook = f"What I worked on this week: {topic}."

    body = [hook, ""]
    if notes:
        body.append("What actually happened:")
        body.extend(f"- {note}" for note in notes)
        body.append("")
    else:
        body.append(
            "The interesting part was not the feature itself, it was the constraint "
            "it forced: every change had to survive a restart without losing state."
        )
        body.append("")

    body.append(
        rng.choice(
            [
                "The fix was smaller than the debugging. It usually is.",
                "Most of the work was deciding what not to build.",
                "The design got simpler once I stopped trying to make it general.",
            ]
        )
    )
    body.append("")
    body.append(
        rng.choice(
            [
                "Next: wiring this into the scheduler and seeing what breaks.",
                "Next up is measuring whether it actually helps.",
                "Still unsure whether this holds up under real load.",
            ]
        )
    )
    return "\n".join(body).strip()


def _default_for_field(name: str, annotation: Any, rng: random.Random) -> Any:
    """Plausible value for one schema field, guided by its name and type."""
    origin = get_origin(annotation)
    lname = name.lower()

    if origin in (list, set, tuple):
        args = get_args(annotation)
        inner = args[0] if args else str
        if inner is str:
            return ["specificity", "concrete example"] if "issue" not in lname else []
        if isinstance(inner, type) and issubclass(inner, BaseModel):
            return []
        return []
    if origin is dict:
        return {}

    # Optional[X] -> use X
    if origin is not None and type(None) in get_args(annotation):
        inner = next((a for a in get_args(annotation) if a is not type(None)), str)
        return _default_for_field(name, inner, rng)

    if annotation is bool:
        return True
    if annotation is int:
        if "probability" in lname:
            return 0
        if any(k in lname for k in ("score", "quality", "depth", "originality", "readability")):
            return rng.randint(72, 93)
        if "count" in lname or "size" in lname:
            return rng.randint(1, 5)
        return rng.randint(1, 10)
    if annotation is float:
        if "probability" in lname:
            return round(rng.uniform(0.04, 0.22), 3)
        if "confidence" in lname:
            return round(rng.uniform(0.75, 0.95), 3)
        return round(rng.uniform(0.5, 0.9), 3)
    if annotation is str:
        if "recommendation" in lname:
            return "APPROVE"
        if "reason" in lname or "why" in lname:
            return "Grounded in work the author actually did this week."
        if "summary" in lname:
            return "Offline mock research summary; no external sources were fetched."
        if "topic" in lname or "title" in lname:
            return "Untitled"
        return ""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _fill_model(annotation, rng)
    return None


def _fill_model(schema: type[T], rng: random.Random) -> T:
    values: dict[str, Any] = {}
    for field_name, field in schema.model_fields.items():
        values[field_name] = _default_for_field(field_name, field.annotation, rng)
    return schema.model_construct(**values)


class MockProvider(LLMProvider):
    """Offline provider. Costs nothing and never leaves the machine."""

    name = "mock"

    def __init__(self, model: str = "mock-1") -> None:
        self.model = model

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 2000,
        task: str = "generic",
        effort: str | None = None,
    ) -> LLMResponse:
        rng = random.Random(_seed_for(prompt + task))
        text = _build_post(prompt, rng)
        return LLMResponse(
            text=text,
            model=self.model,
            provider=self.name,
            prompt_tokens=len(prompt) // 4,
            completion_tokens=len(text) // 4,
            estimated_cost_usd=0.0,
            stop_reason="end_turn",
        )

    def structured_generate(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        max_tokens: int = 2000,
        task: str = "generic",
        effort: str | None = None,
    ) -> LLMResponse:
        rng = random.Random(_seed_for(prompt + task + schema.__name__))
        instance = _fill_model(schema, rng)

        # Give the fields that drive real decisions topic-aware values.
        topic = _extract_topic(prompt)
        for field_name in schema.model_fields:
            if field_name in {"topic", "title"}:
                setattr(instance, field_name, topic[:200])
            elif field_name == "content":
                setattr(instance, field_name, _build_post(prompt, rng))

        return LLMResponse(
            text=instance.model_dump_json(),
            model=self.model,
            provider=self.name,
            prompt_tokens=len(prompt) // 4,
            completion_tokens=120,
            estimated_cost_usd=0.0,
            stop_reason="end_turn",
            parsed=instance,
        )

    def health_check(self) -> ProviderStatus:
        return ProviderStatus(
            status="ok",
            detail="Offline mock provider - deterministic output, no API calls, no cost.",
            extra={"model": self.model},
        )
