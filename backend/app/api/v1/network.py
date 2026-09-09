"""Networking recommendations.

There is intentionally no endpoint here that sends a connection request,
follows, messages, likes or comments. The API surface is read, add candidate,
and record what the user decided - the invitation itself happens in LinkedIn,
by hand.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.schemas import ConnectionActionRequest, ConnectionOut
from app.core.errors import NotFoundError
from app.core.logging import log_event
from app.database.enums import ConnectionStatus
from app.database.models import ConnectionCandidate, Device
from app.database.session import get_db
from app.networking.service import CandidateInput, add_candidate, recommendation_limit
from app.security.auth import get_current_device

log = logging.getLogger(__name__)
router = APIRouter(prefix="/network", tags=["network"])


class AddCandidateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    profile_url: str = Field(min_length=1, max_length=1000)
    role: str | None = None
    company: str | None = None
    context: str = Field(default="", max_length=2000)
    shared_interests: list[str] | None = None


@router.get("", response_model=list[ConnectionOut])
def list_candidates(
    status: ConnectionStatus | None = Query(default=None),
    limit: int = Query(default=25, le=100),
    db: Session = Depends(get_db),
    _: Device = Depends(get_current_device),
) -> list[ConnectionOut]:
    stmt = select(ConnectionCandidate).order_by(ConnectionCandidate.relevance_score.desc())
    if status is not None:
        stmt = stmt.where(ConnectionCandidate.status == status)
    else:
        stmt = stmt.where(ConnectionCandidate.status == ConnectionStatus.NEW)
    rows = db.execute(stmt.limit(min(limit, recommendation_limit(db) * 5))).scalars().all()
    return [ConnectionOut.model_validate(row) for row in rows]


@router.post("", response_model=ConnectionOut | None)
def create_candidate(
    payload: AddCandidateRequest,
    db: Session = Depends(get_db),
    _: Device = Depends(get_current_device),
) -> ConnectionOut | None:
    """Add someone the user came across, and draft a note for them."""
    record = add_candidate(
        db,
        CandidateInput(
            name=payload.name,
            profile_url=payload.profile_url,
            role=payload.role,
            company=payload.company,
            context=payload.context,
            shared_interests=payload.shared_interests,
        ),
    )
    db.commit()
    return ConnectionOut.model_validate(record) if record else None


@router.post("/{candidate_id}/status", response_model=ConnectionOut)
def set_status(
    candidate_id: int,
    payload: ConnectionActionRequest,
    db: Session = Depends(get_db),
    device: Device = Depends(get_current_device),
) -> ConnectionOut:
    """Record what the user did: opened the profile, skipped, saved, connected.

    MARKED_CONNECTED means the user sent the invitation themselves - the
    system has no way to send one.
    """
    candidate = db.get(ConnectionCandidate, candidate_id)
    if candidate is None:
        raise NotFoundError("That recommendation no longer exists.")
    candidate.status = payload.status
    db.commit()
    log_event(
        log,
        "CONNECTION_STATUS_SET",
        candidate_id=candidate.id,
        status=str(payload.status),
        device_id=device.id,
    )
    return ConnectionOut.model_validate(candidate)
