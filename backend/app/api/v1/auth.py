"""Device pairing.

The pairing code is generated on the laptop (``scripts/pair.py`` prints it,
with a QR code) and never handed out over the network. That is deliberate: an
endpoint that issued codes to anonymous callers would let anyone on the LAN
pair themselves. The only unauthenticated route here is redeeming a code that
the user is physically looking at.
"""

from __future__ import annotations

import logging
import time
from collections import deque

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.schemas import DeviceInfo, PairRequest, PairResponse
from app.core.logging import log_event
from app.core.settings_store import get_setting
from app.database.base import utcnow
from app.database.models import Device, PairingCode
from app.database.session import get_db
from app.security.auth import get_current_device
from app.security.tokens import generate_device_token, new_device_id, verify_pairing_code

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

DEFAULT_SCOPES = [
    "drafts:read",
    "drafts:write",
    "approvals:write",
    "network:read",
    "analytics:read",
]

# Brute-force guard for the one unauthenticated route. Codes are short enough
# to be typed, so attempts are capped globally as well as per code.
_MAX_ATTEMPTS_PER_WINDOW = 10
_WINDOW_SECONDS = 60
_attempts: deque[float] = deque()


def _rate_limit() -> None:
    now = time.monotonic()
    while _attempts and now - _attempts[0] > _WINDOW_SECONDS:
        _attempts.popleft()
    if len(_attempts) >= _MAX_ATTEMPTS_PER_WINDOW:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "too_many_attempts",
                "message": "Too many pairing attempts. Wait a minute and generate a fresh code.",
                "recovery": "Run scripts/pair.py again on the laptop.",
            },
        )
    _attempts.append(now)


@router.post("/pair", response_model=PairResponse)
def pair_device(
    payload: PairRequest, request: Request, db: Session = Depends(get_db)
) -> PairResponse:
    _rate_limit()
    now = utcnow()

    candidates = (
        db.execute(
            select(PairingCode)
            .where(PairingCode.used_at.is_(None), PairingCode.expires_at > now)
            .order_by(PairingCode.id.desc())
        )
        .scalars()
        .all()
    )

    matched: PairingCode | None = None
    for candidate in candidates:
        candidate.attempts += 1
        if candidate.attempts > 8:
            continue
        if verify_pairing_code(payload.code, candidate.code_hash):
            matched = candidate
            break

    if matched is None:
        db.commit()
        log_event(
            log,
            "PAIRING_FAILED",
            level=logging.WARNING,
            client=request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "invalid_pairing_code",
                "message": "That pairing code is not valid or has expired.",
                "recovery": "Generate a new code on the laptop and try again.",
            },
        )

    device_id = new_device_id()
    token, token_hash = generate_device_token(device_id)
    device = Device(
        id=device_id,
        name=payload.device_name,
        platform=payload.platform,
        token_hash=token_hash,
        scopes=DEFAULT_SCOPES,
        paired_at=now,
        last_seen_at=now,
    )
    db.add(device)

    matched.used_at = now
    matched.consumed_by_device = device_id
    db.commit()

    log_event(log, "DEVICE_PAIRED", device_id=device_id, device_name=payload.device_name)
    return PairResponse(
        device_id=device_id,
        token=token,
        server_name="LinkedIn Content Copilot",
        api_version="v1",
        timezone=get_setting(db, "timezone"),
    )


@router.get("/me", response_model=DeviceInfo)
def whoami(device: Device = Depends(get_current_device)) -> DeviceInfo:
    return DeviceInfo.model_validate(device)


@router.post("/revoke", status_code=status.HTTP_204_NO_CONTENT)
def revoke_self(
    device: Device = Depends(get_current_device), db: Session = Depends(get_db)
) -> None:
    """Unpair this device. The token stops working immediately."""
    device.revoked = True
    device.revoked_at = utcnow()
    db.commit()
    log_event(log, "DEVICE_REVOKED", device_id=device.id)


LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
DESKTOP_DEVICE_NAME = "This computer"


@router.post("/desktop-session", response_model=PairResponse)
def desktop_session(request: Request, db: Session = Depends(get_db)) -> PairResponse:
    """Issue a token to a client running on this machine.

    The desktop GUI and the Jarvis agent run on the same computer as the
    backend, so making the user copy a pairing code between two local processes
    is friction with no security benefit - anything that can reach loopback can
    already read the database file directly.

    This is refused for any non-loopback caller, so a phone or anything else on
    the LAN still has to pair properly with a one-time code.
    """
    client_host = request.client.host if request.client else ""
    if client_host not in LOOPBACK_HOSTS:
        log_event(
            log,
            "DESKTOP_SESSION_REFUSED",
            level=logging.WARNING,
            client=client_host,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "not_local",
                "message": "Desktop sessions are only available on this computer.",
                "recovery": "Pair this device with a one-time code instead.",
            },
        )

    now = utcnow()
    existing = db.execute(
        select(Device).where(
            Device.name == DESKTOP_DEVICE_NAME,
            Device.platform == "desktop",
            Device.revoked.is_(False),
        )
    ).scalars().first()

    # Rotate the secret on every request: the token is only ever held in the
    # memory of the local process that asked for it.
    device_id = existing.id if existing is not None else new_device_id()
    token, token_hash = generate_device_token(device_id)

    if existing is None:
        db.add(
            Device(
                id=device_id,
                name=DESKTOP_DEVICE_NAME,
                platform="desktop",
                token_hash=token_hash,
                scopes=DEFAULT_SCOPES,
                paired_at=now,
                last_seen_at=now,
            )
        )
    else:
        existing.token_hash = token_hash
        existing.last_seen_at = now

    db.commit()
    log_event(log, "DESKTOP_SESSION_ISSUED", device_id=device_id)
    return PairResponse(
        device_id=device_id,
        token=token,
        server_name="LinkedIn Content Copilot",
        api_version="v1",
        timezone=get_setting(db, "timezone"),
    )
