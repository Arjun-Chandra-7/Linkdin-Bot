"""SQLAlchemy declarative base and shared column helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    """Timezone-aware "now". All stored timestamps are UTC; the user's local
    timezone is applied only at presentation/scheduling boundaries."""
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """A datetime column that is always timezone-aware UTC in Python.

    SQLite has no native timezone support: it silently stores whatever it is
    given and hands back naive datetimes, which then blow up when compared
    against an aware ``utcnow()``. Rather than sprinkling tzinfo checks across
    every comparison, normalisation happens once, here - values are coerced to
    UTC on the way in and re-tagged as UTC on the way out.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, server_default=func.now()
    )
