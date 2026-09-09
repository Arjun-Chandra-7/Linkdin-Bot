"""Authentication dependencies.

Every ``/api/v1`` route except pairing and the unauthenticated health probe
requires a paired-device bearer token. There is no anonymous access, so the
server can be exposed on the LAN without handing control to anyone who finds
the port.
"""

from __future__ import annotations

import logging

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.logging import log_event
from app.database.base import utcnow
from app.database.models import Device
from app.database.session import get_db
from app.security.tokens import parse_token, verify_token_secret

log = logging.getLogger(__name__)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail={"code": "unauthorized", "message": "Device is not paired or the token is invalid."},
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_device(
    request: Request,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Device:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _UNAUTHORIZED

    parsed = parse_token(authorization.split(" ", 1)[1].strip())
    if parsed is None:
        raise _UNAUTHORIZED

    device_id, secret = parsed
    device = db.get(Device, device_id)
    if device is None or device.revoked:
        log_event(
            log,
            "AUTH_REJECTED",
            level=logging.WARNING,
            device_id=device_id,
            reason="unknown_or_revoked",
            path=request.url.path,
        )
        raise _UNAUTHORIZED

    if not verify_token_secret(secret, device.token_hash):
        log_event(
            log,
            "AUTH_REJECTED",
            level=logging.WARNING,
            device_id=device_id,
            reason="bad_secret",
            path=request.url.path,
        )
        raise _UNAUTHORIZED

    device.last_seen_at = utcnow()
    db.commit()
    return device
