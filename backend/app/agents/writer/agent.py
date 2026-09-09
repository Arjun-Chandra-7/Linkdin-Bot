"""The writer agent.

Turns an idea (plus any research) into one or more drafts, scores them, drops
the ones that do not clear the quality gate, and only then puts the survivor
in front of the user.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.agents.quality.detector import analyze
from app.agents.writer.dedupe import find_duplicate
from app.agents.writer.style import learn_style_notes, preferred_length_range
from app.approvals.service import add_version
from app.content.prompts import BASE_SYSTEM, build_rewrite_prompt, build_writer_prompt
from app.content.text import canonicalize, content_hash
from app.core.logging import log_event
from app.core.settings_store import get_setting
from app.database.enums import (
    ContentCategory,
    DraftStatus,
    IdeaStatus,
    NotificationPriority,
    NotificationType,
    PostType,
    VersionOrigin,
)
from app.database.models import Draft, Idea, Research
from app.llm.factory import MeteredLLM
from app.notifications.service import notify

log = logging.getLogger(__name__)

# Which format suits which kind of idea, when nothing more specific is known.
CATEGORY_DEFAULT_TYPE: dict[ContentCategory, PostType] = {
    ContentCategory.BUILD_LOG: PostType.BUILD_LOG,
    ContentCategory.TECHNICAL_LESSON: PostType.TECHNICAL_BREAKDOWN,
    ContentCategory.AI_OBSERVATION: PostType.NEWS_WITH_ANALYSIS,
    ContentCategory.MILESTONE: PostType.MILESTONE,
}


@dataclass
class WriteOutcome:
    draft: Draft | None
    accepted: bool
    reason: str
    quality: dict | None = None


def choose_post_type(idea: Idea) -> PostType:
    explicit = (idea.extra or {}).get("post_type")
    if explicit:
        try:
            return PostType(explicit)
        except ValueError:
            pass
    return CATEGORY_DEFAULT_TYPE.get(ContentCategory(idea.category), PostType.BUILD_LOG)


def _research_for(db: Session, idea: Idea) -> Research | None:
    return next(iter(sorted(idea.research, key=lambda r: r.id, reverse=True)), None)


def generate_drafts(db: Session, idea: Idea) -> WriteOutcome:
    """Write, score and (if good enough) queue a draft for review."""
    llm = MeteredLLM(db)
    research = _research_for(db, idea)
    post_type = choose_post_type(idea)

    style_notes = learn_style_notes(db)
    target_range = preferred_length_range(
        db, tuple(get_setting(db, "preferred_length_range"))  # type: ignore[arg-type]
    )
    min_quality = int(get_setting(db, "quality_threshold"))
    max_slop = float(get_setting(db, "ai_slop_max_probability"))
    dup_threshold = float(get_setting(db, "duplicate_similarity_threshold"))

    # Only genuinely promising ideas are worth three generations.
    variants = ["A", "B", "C"] if idea.final_score >= float(
        get_setting(db, "multi_variant_threshold")
    ) else ["A"]

    draft = Draft(
        idea_id=idea.id,
        title=idea.topic[:300],
        post_type=post_type,
        category=idea.category,
        status=DraftStatus.DRAFT,
        generation_reason=idea.why_it_matters,
    )
    db.add(draft)
    db.flush()

    evidence = [
        claim.get("statement", "")
        for claim in (research.claims if research else [])
        if claim.get("statement")
    ]

    scored: list[tuple[float, str, str, dict]] = []
    for variant in variants:
        prompt = build_writer_prompt(
            topic=idea.topic,
            post_type=post_type,
            why_it_matters=idea.why_it_matters,
            source_notes=idea.summary,
            research_summary=research.summary if research else None,
            evidence=evidence,
            uncertainty=research.uncertainty_notes if research else None,
            variant=variant,
            target_range=target_range,
            style_notes=style_notes,
        )
        response = llm.generate(
            prompt, system=BASE_SYSTEM, task="generate_draft", max_tokens=1600
        )
        text = canonicalize(response.text)
        if not text:
            continue
        report = analyze(text, claim_confidence=research.confidence if research else 0.8)
        scored.append((report.quality, variant, text, report.to_dict()))

    if not scored:
        draft.status = DraftStatus.FAILED
        draft.failure_reason = "The model returned no usable text."
        db.flush()
        return WriteOutcome(draft=draft, accepted=False, reason="empty_generation")

    scored.sort(key=lambda item: item[0], reverse=True)

    # Persist every variant so the user can pick a different one on the phone.
    seen_hashes: set[str] = set()
    for _, variant, text, quality in scored:
        digest = content_hash(text)
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        add_version(
            db,
            draft,
            text,
            label=variant,
            origin=VersionOrigin.LLM,
            quality=quality,
            make_current=False,
        )

    best_quality, best_variant, best_text, best_report = scored[0]
    best_version = next(v for v in draft.versions if v.label == best_variant)
    draft.current_version = best_version
    draft.status = DraftStatus.QUALITY_CHECK
    db.flush()

    duplicate = find_duplicate(db, best_text, threshold=dup_threshold, exclude_draft_id=draft.id)
    if duplicate is not None:
        draft.status = DraftStatus.REJECTED
        draft.rejection_reason = "ALREADY_POSTED_SIMILAR"
        draft.rejection_note = (
            f"Too similar ({duplicate.score:.0%}) to an existing "
            f"{duplicate.kind} (#{duplicate.reference_id})."
        )
        idea.status = IdeaStatus.ARCHIVED
        db.flush()
        log_event(
            log, "DRAFT_REJECTED_DUPLICATE", draft_id=draft.id, score=round(duplicate.score, 3)
        )
        return WriteOutcome(draft=draft, accepted=False, reason="duplicate", quality=best_report)

    if best_report["recommendation"] == "REJECT" or best_quality < min_quality or (
        best_report["ai_slop_probability"] > max_slop
    ):
        # Rejected by the machine, so the user's phone never sees it.
        draft.status = DraftStatus.REJECTED
        draft.rejection_reason = "SOUNDS_AI_GENERATED"
        draft.rejection_note = "; ".join(best_report["issues"][:3]) or "Below the quality threshold."
        idea.status = IdeaStatus.ARCHIVED
        db.flush()
        log_event(
            log,
            "DRAFT_REJECTED_QUALITY",
            draft_id=draft.id,
            quality=best_quality,
            slop=best_report["ai_slop_probability"],
        )
        return WriteOutcome(draft=draft, accepted=False, reason="quality_gate", quality=best_report)

    draft.status = DraftStatus.READY_FOR_REVIEW
    idea.status = IdeaStatus.DRAFTED
    db.flush()

    notify(
        db,
        type=NotificationType.APPROVAL_READY,
        title="New post ready for review",
        body=draft.title,
        priority=NotificationPriority.NORMAL,
        payload={"draft_id": draft.id, "quality": best_quality},
        dedupe_key=f"approval-ready:{draft.id}",
    )
    log_event(
        log,
        "POST_GENERATED",
        draft_id=draft.id,
        variants=len(scored),
        quality=best_quality,
        post_type=str(post_type),
    )
    return WriteOutcome(draft=draft, accepted=True, reason="ready", quality=best_report)


def rewrite(
    db: Session,
    draft: Draft,
    *,
    operation: str,
    instruction: str | None = None,
    paragraph_index: int | None = None,
) -> Draft:
    """Apply a targeted rewrite requested from the phone."""
    version = draft.current_version
    if version is None:
        raise ValueError("Draft has no content to rewrite")

    paragraphs = [p for p in version.content.split("\n\n") if p.strip()]
    paragraph = (
        paragraphs[paragraph_index]
        if paragraph_index is not None and 0 <= paragraph_index < len(paragraphs)
        else None
    )

    llm = MeteredLLM(db)
    response = llm.generate(
        build_rewrite_prompt(
            content=version.content,
            operation=operation,
            instruction=instruction,
            paragraph=paragraph,
        ),
        system=BASE_SYSTEM,
        task=f"rewrite:{operation}",
        max_tokens=1600,
    )
    text = canonicalize(response.text)
    if not text:
        raise ValueError("The model returned no text")

    report = analyze(text)
    add_version(
        db,
        draft,
        text,
        label=f"{version.label}-{operation}",
        origin=VersionOrigin.REGENERATED,
        quality=report.to_dict(),
        notes=f"Rewritten on device: {operation}",
        invalidate_reason=f"Regenerated ({operation})",
    )
    if draft.status in {DraftStatus.SAVED_FOR_LATER, DraftStatus.QUALITY_CHECK}:
        draft.status = DraftStatus.READY_FOR_REVIEW
    db.flush()
    log_event(log, "DRAFT_REWRITTEN", draft_id=draft.id, operation=operation, quality=report.quality)
    return draft
