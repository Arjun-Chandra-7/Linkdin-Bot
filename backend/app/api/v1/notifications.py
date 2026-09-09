"""Notification delivery to the paired device."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.schemas import NotificationOut
from app.core.errors import NotFoundError
from app.database.base import utcnow
from app.database.models import Device, Notification
from app.database.session import get_db
from app.notifications.service import mark_delivered, pending_for_device
from app.security.auth import get_current_device

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/pending", response_model=list[NotificationOut])
def get_pending(
    ack: bool = True,
    db: Session = Depends(get_db),
    device: Device = Depends(get_current_device),
) -> list[NotificationOut]:
    """Fetch undelivered notifications; the app raises them locally.

    ``ack=true`` marks them delivered in the same call so the phone cannot be
    notified twice about the same event.
    """
    rows = pending_for_device(db, device.id)
    out = [NotificationOut.model_validate(n) for n in rows]
    if ack and rows:
        mark_delivered(db, rows)
        db.commit()
    return out


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    _: Device = Depends(get_current_device),
) -> NotificationOut:
    notification = db.get(Notification, notification_id)
    if notification is None:
        raise NotFoundError("That notification no longer exists.")
    notification.read_at = utcnow()
    db.commit()
    return NotificationOut.model_validate(notification)
