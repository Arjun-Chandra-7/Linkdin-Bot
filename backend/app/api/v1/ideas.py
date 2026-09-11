"""Public-source topic suggestions for the content queue."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.enums import IdeaStatus, SourceType
from app.database.models import Device, Idea, Job, Source
from app.database.session import get_db
from app.jobs.queue import enqueue
from app.security.auth import get_current_device

router = APIRouter(prefix="/ideas", tags=["ideas"])


class IdeaSuggestion(BaseModel):
    rank: int
    idea_id: int
    topic: str
    summary: str | None = None
    source: str
    source_url: str | None = None
    published_at: datetime | None = None
    score: float
    timeliness: float


class IdeaSuggestions(BaseModel):
    items: list[IdeaSuggestion]
    refresh_queued: bool


def _suggestions(db: Session, limit: int) -> list[Idea]:
    active = [IdeaStatus.SCORED, IdeaStatus.RESEARCHED]
    rss = list(
        db.execute(
            select(Idea)
            .join(Source, Idea.source_id == Source.id)
            .where(Idea.status.in_(active), Source.type == SourceType.RSS)
            .order_by(Idea.timeliness_score.desc(), Idea.final_score.desc(), Idea.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    if len(rss) >= limit:
        return rss
    seen = {idea.id for idea in rss}
    fallback = (
        db.execute(
            select(Idea)
            .where(Idea.status.in_(active), Idea.id.not_in(seen or [-1]))
            .order_by(Idea.timeliness_score.desc(), Idea.final_score.desc(), Idea.id.desc())
            .limit(limit - len(rss))
        )
        .scalars()
        .all()
    )
    return rss + fallback


@router.get("/top", response_model=IdeaSuggestions)
def top_ideas(
    limit: int = Query(default=10, ge=1, le=10),
    db: Session = Depends(get_db),
    _: Device = Depends(get_current_device),
) -> IdeaSuggestions:
    """Return ranked topics and ask the worker to refresh public feeds."""
    now = datetime.now(UTC)
    key = f"manual:discover:{now.date().isoformat()}:{now.hour}"
    existing = db.execute(select(Job).where(Job.idempotency_key == key)).scalar_one_or_none()
    enqueue(db, "discover_topics", {}, idempotency_key=key)
    db.commit()

    selected = _suggestions(db, limit)
    for idea in selected:
        if idea.status == IdeaStatus.SCORED:
            enqueue(
                db,
                "research_topic",
                {"idea_id": idea.id},
                idempotency_key=f"research:{idea.id}",
            )
    db.commit()

    rows: list[IdeaSuggestion] = []
    for rank, idea in enumerate(selected, 1):
        source = db.get(Source, idea.source_id) if idea.source_id else None
        rows.append(
            IdeaSuggestion(
                rank=rank,
                idea_id=idea.id,
                topic=idea.topic,
                summary=idea.summary,
                source=source.name if source else "User material",
                source_url=idea.source_ref,
                published_at=idea.published_at,
                score=idea.final_score,
                timeliness=idea.timeliness_score,
            )
        )
    return IdeaSuggestions(items=rows, refresh_queued=existing is None)
