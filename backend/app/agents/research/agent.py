"""Research agent.

Runs before writing whenever a topic involves factual claims. The output is
stored with per-claim confidence so the writer can hedge or omit rather than
assert something unverified.

The rule the prompt enforces, and the schema records: never invent numbers,
benchmarks, results or quotes. Unknown is a valid answer.
"""

from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.discovery.sources import USER_AGENT, _strip_html
from app.core.logging import log_event
from app.database.enums import ContentCategory
from app.database.models import Idea, Research
from app.llm.factory import MeteredLLM

log = logging.getLogger(__name__)

MAX_PAGE_CHARS = 6000


class Claim(BaseModel):
    statement: str = Field(description="A single factual claim, stated plainly.")
    confidence: float = Field(default=0.5, description="0-1 confidence this is accurate.")
    support: str = Field(default="", description="Where this came from.")


class Reference(BaseModel):
    title: str = ""
    url: str = ""
    published_at: str = ""
    note: str = ""


class ResearchOutput(BaseModel):
    summary: str = Field(description="What is actually known about this topic.")
    claims: list[Claim] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    uncertainty_notes: str = Field(
        default="", description="What is NOT known, or could not be verified."
    )
    confidence: float = Field(default=0.5, description="Overall confidence, 0-1.")


RESEARCH_SYSTEM = """You are a careful research assistant for a technical writer.

Your job is to separate what is actually known from what is not.

Absolute rules:
- Never invent numbers, benchmarks, dates, company names, quotes, user counts, \
revenue figures or performance results.
- If a detail is not present in the material you were given, it does not go in \
a claim. Put it in uncertainty_notes instead.
- Prefer fewer, well-supported claims over many vague ones.
- Assign honest confidence. 0.9 means the source states it directly. 0.5 means \
it is implied. Below 0.4 means you are guessing - do not include it as a claim."""


def _fetch_page(url: str) -> str:
    try:
        with httpx.Client(timeout=20.0, headers={"User-Agent": USER_AGENT}) as client:
            response = client.get(url, follow_redirects=True)
            response.raise_for_status()
            if "html" not in response.headers.get("content-type", "").lower():
                return ""
            return _strip_html(response.text)[:MAX_PAGE_CHARS]
    except httpx.HTTPError as exc:
        log_event(log, "RESEARCH_FETCH_FAILED", url=url, error=type(exc).__name__)
        return ""


def research_idea(db: Session, idea: Idea, *, fetch_source_page: bool = True) -> Research:
    """Gather and store evidence for one idea."""
    material_parts = [f"TOPIC: {idea.topic}"]
    if idea.summary:
        material_parts.append(f"SOURCE SUMMARY:\n{idea.summary}")

    page_text = ""
    if fetch_source_page and idea.source_ref and idea.source_ref.startswith("http"):
        page_text = _fetch_page(idea.source_ref)
        if page_text:
            material_parts.append(f"SOURCE PAGE CONTENT:\n{page_text}")

    # For the user's own work the evidence is the commit/release record itself,
    # so there is nothing external to verify and confidence is inherently high.
    is_own_work = ContentCategory(idea.category) in {
        ContentCategory.BUILD_LOG,
        ContentCategory.MILESTONE,
    }
    if is_own_work:
        material_parts.append(
            "NOTE: This describes the author's own work. Treat the details above as "
            "first-hand evidence, but still do not invent specifics that are absent."
        )

    prompt = "\n\n".join(material_parts) + (
        "\n\nExtract what is genuinely known about this topic, with honest confidence "
        "for each claim, and state clearly what could not be verified."
    )

    llm = MeteredLLM(db)
    output = llm.structured(
        prompt, ResearchOutput, task="research_topic", system=RESEARCH_SYSTEM, max_tokens=1500
    )

    references = [ref.model_dump() for ref in output.references]
    if idea.source_ref and not any(r.get("url") == idea.source_ref for r in references):
        references.insert(
            0,
            {
                "title": idea.topic[:200],
                "url": idea.source_ref,
                "published_at": idea.published_at.isoformat() if idea.published_at else "",
                "note": "Original source",
            },
        )

    research = Research(
        idea_id=idea.id,
        summary=output.summary or (idea.summary or idea.topic),
        claims=[claim.model_dump() for claim in output.claims if claim.confidence >= 0.4],
        references=references,
        contradictions=output.contradictions,
        uncertainty_notes=output.uncertainty_notes or None,
        confidence=max(
            0.0, min(1.0, output.confidence if not is_own_work else max(output.confidence, 0.8))
        ),
    )
    db.add(research)
    db.flush()

    log_event(
        log,
        "RESEARCH_COMPLETED",
        idea_id=idea.id,
        claims=len(research.claims),
        confidence=round(research.confidence, 2),
        fetched_page=bool(page_text),
    )
    return research
