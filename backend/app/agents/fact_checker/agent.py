"""Fact checker.

Runs over a finished draft and looks for assertions the research does not
support - invented numbers being the failure mode that matters most, since a
fabricated benchmark in a public post is expensive to take back.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.logging import log_event
from app.database.models import Research
from app.llm.factory import MeteredLLM

log = logging.getLogger(__name__)

# Assertions with hard numbers are the highest-risk thing in a draft.
NUMERIC_CLAIM = re.compile(
    r"[^.!?\n]*\b\d+(?:\.\d+)?\s*(?:%|x|ms|s|seconds?|minutes?|hours?|days?|weeks?|"
    r"users?|customers?|requests?|times faster|k|m|gb|mb)\b[^.!?\n]*",
    re.I,
)


class FlaggedClaim(BaseModel):
    statement: str
    reason: str = ""
    severity: str = Field(default="review", description="review | remove")


class FactCheckOutput(BaseModel):
    unsupported_claims: list[FlaggedClaim] = Field(default_factory=list)
    verdict: str = Field(default="ok", description="ok | needs_review | unsafe")
    notes: str = ""


FACT_CHECK_SYSTEM = """You check a draft social post against the evidence gathered for it.

Flag any statement that asserts a fact the evidence does not support - especially \
numbers, benchmarks, dates, named people or companies, and claimed results.

Do NOT flag:
- opinions clearly framed as the author's view
- descriptions of the author's own work that match the evidence
- hedged statements ("I think", "it seems", "roughly")

Return only genuine problems. An empty list is the correct answer for a clean draft."""


def check_draft(db: Session, content: str, research: Research | None) -> dict:
    """Return a structured fact-check report for a draft."""
    evidence_lines = [
        f"- {claim.get('statement', '')} (confidence {claim.get('confidence', 0):.2f})"
        for claim in (research.claims if research else [])
    ]
    numeric_statements = [match.strip() for match in NUMERIC_CLAIM.findall(content)][:10]

    # With no evidence at all, any hard number in the draft is unverifiable by
    # definition - say so rather than pretending it was checked.
    if research is None or not evidence_lines:
        flagged = [
            {
                "statement": statement,
                "reason": "No research evidence was gathered for this post.",
                "severity": "review",
            }
            for statement in numeric_statements
        ]
        report = {
            "verdict": "needs_review" if flagged else "ok",
            "unsupported_claims": flagged,
            "notes": "No research was available; numeric claims could not be verified.",
            "checked": bool(flagged),
        }
        return report

    prompt = (
        "EVIDENCE:\n"
        + "\n".join(evidence_lines)
        + (
            f"\n\nKNOWN UNCERTAINTY: {research.uncertainty_notes}"
            if research.uncertainty_notes
            else ""
        )
        + f"\n\nDRAFT POST:\n{content}\n\nFlag only statements the evidence does not support."
    )

    llm = MeteredLLM(db)
    output = llm.structured(
        prompt, FactCheckOutput, task="fact_check", system=FACT_CHECK_SYSTEM, max_tokens=900
    )

    report = {
        "verdict": output.verdict,
        "unsupported_claims": [claim.model_dump() for claim in output.unsupported_claims],
        "notes": output.notes,
        "checked": True,
        "evidence_count": len(evidence_lines),
    }
    if report["unsupported_claims"]:
        log_event(
            log,
            "FACT_CHECK_FLAGGED",
            level=logging.WARNING,
            flagged=len(report["unsupported_claims"]),
            verdict=output.verdict,
        )
    return report


def confidence_from_report(report: dict, base: float = 0.85) -> float:
    """Translate a fact-check report into a claim-confidence multiplier."""
    flagged = len(report.get("unsupported_claims", []))
    if report.get("verdict") == "unsafe":
        return 0.25
    return max(0.2, base - flagged * 0.15)
