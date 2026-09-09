"""Shared router dependencies and small view helpers."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.schemas import DraftDetail, DraftSummary, DraftVersionOut, ResearchReference
from app.approvals.service import valid_approval_for
from app.database.models import Draft, Research


def _preview(text: str, limit: int = 220) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def draft_summary(draft: Draft) -> DraftSummary:
    version = draft.current_version
    quality = (version.quality or {}) if version else {}
    return DraftSummary(
        id=draft.id,
        title=draft.title,
        post_type=draft.post_type,
        category=draft.category,
        status=draft.status,
        created_at=draft.created_at,
        proposed_publish_at=draft.proposed_publish_at,
        quality_score=quality.get("quality"),
        ai_slop_probability=quality.get("ai_slop_probability"),
        char_count=version.char_count if version else None,
        hook=version.hook if version else None,
        preview=_preview(version.content) if version else None,
        version_count=len(draft.versions),
    )


def draft_detail(db: Session, draft: Draft) -> DraftDetail:
    base = draft_summary(draft).model_dump()
    version = draft.current_version

    references: list[ResearchReference] = []
    research_summary = None
    uncertainty = None
    if draft.idea_id:
        research = (
            db.execute(
                select(Research)
                .where(Research.idea_id == draft.idea_id)
                .order_by(Research.id.desc())
            )
            .scalars()
            .first()
        )
        if research:
            research_summary = research.summary
            uncertainty = research.uncertainty_notes
            references = [ResearchReference(**ref) for ref in (research.references or [])]

    return DraftDetail(
        **base,
        generation_reason=draft.generation_reason,
        current_version=DraftVersionOut.model_validate(version) if version else None,
        versions=[DraftVersionOut.model_validate(v) for v in draft.versions],
        sources=references,
        research_summary=research_summary,
        uncertainty_notes=uncertainty,
        predicted_performance=draft.predicted_performance,
        has_valid_approval=valid_approval_for(db, draft) is not None,
        rejection_reason=draft.rejection_reason,
        failure_reason=draft.failure_reason,
    )


def count_where(db: Session, model, *conditions) -> int:
    stmt = select(func.count()).select_from(model)
    if conditions:
        stmt = stmt.where(*conditions)
    return int(db.execute(stmt).scalar_one())
