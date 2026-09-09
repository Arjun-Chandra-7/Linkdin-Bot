"""Notification queue.

There is no cloud push service in this design - the backend runs on the user's
laptop on the local network. The server records notifications here, the phone
polls (or holds a WebSocket) and raises a *local* Android notification. That
keeps the system dependency-free and working offline on a LAN, at the cost of
notifications arriving only while the app can reach the backend.

Volume control: high-priority events always go out immediately; low-priority
ones are deferred past quiet hours so the phone is not buzzed at night.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logging import log_event
from app.core.settings_store import get_setting
from app.database.base import utcnow
from app.database.enums import NotificationPriority, NotificationType
from app.database.models import Notification

log = logging.getLogger(__name__)


def _parse_hhmm(value: str, fallback: tuple[int, int]) -> tuple[int, int]:
    try:
        hour, minute = (int(p) for p in str(value).split(":")[:2])
        return hour, minute
    except (ValueError, TypeError):
        return fallback


def next_delivery_time(db: Session, priority: NotificationPriority) -> datetime | None:
    """When this notification may be shown. ``None`` means immediately."""
    if priority is NotificationPriority.HIGH:
        return None
    quiet = get_setting(db, "quiet_hours") or {}
    if not quiet:
        return None

    try:
        tz = ZoneInfo(get_setting(db, "timezone"))
    except Exception:  # pragma: no cover
        return None

    start_h, start_m = _parse_hhmm(quiet.get("start", "22:30"), (22, 30))
    end_h, end_m = _parse_hhmm(quiet.get("end", "07:30"), (7, 30))

    now_local = utcnow().astimezone(tz)
    start = now_local.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    end = now_local.replace(hour=end_h, minute=end_m, second=0, microsecond=0)

    # Quiet window normally wraps midnight (22:30 -> 07:30).
    in_quiet = now_local >= start or now_local < end if start > end else start <= now_local < end
    if not in_quiet:
        return None
    resume = end if now_local < end else end + timedelta(days=1)
    return resume.astimezone(utcnow().tzinfo)


def notify(
    db: Session,
    *,
    type: NotificationType,
    title: str,
    body: str,
    payload: dict | None = None,
    priority: NotificationPriority = NotificationPriority.NORMAL,
    dedupe_key: str | None = None,
    device_id: str | None = None,
) -> Notification | None:
    """Queue a notification. Returns ``None`` if it was a duplicate."""
    if not get_setting(db, "notifications_enabled"):
        return None

    if dedupe_key:
        existing = db.execute(
            select(Notification).where(Notification.dedupe_key == dedupe_key)
        ).scalar_one_or_none()
        if existing is not None:
            return None

    notification = Notification(
        type=type,
        priority=priority,
        title=title,
        body=body,
        payload=payload or {},
        device_id=device_id,
        dedupe_key=dedupe_key,
        deliver_after=next_delivery_time(db, priority),
    )
    db.add(notification)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return None

    log_event(log, "NOTIFICATION_QUEUED", type=str(type), priority=str(priority), title=title)
    return notification


def pending_for_device(db: Session, device_id: str, limit: int = 50) -> list[Notification]:
    """Undelivered notifications whose hold time has passed."""
    now = utcnow()
    rows = (
        db.execute(
            select(Notification)
            .where(
                Notification.delivered_at.is_(None),
                (Notification.device_id.is_(None)) | (Notification.device_id == device_id),
                (Notification.deliver_after.is_(None)) | (Notification.deliver_after <= now),
            )
            .order_by(Notification.priority, Notification.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return rows


def mark_delivered(db: Session, notifications: list[Notification]) -> None:
    now = utcnow()
    for notification in notifications:
        notification.delivered_at = now
    db.flush()
