"""Lightweight, ordered schema migrations.

Alembic is deliberately avoided: this is a single-user SQLite deployment and a
small explicit runner is easier to reason about, test and recover from. Every
migration is applied exactly once and recorded in ``schema_migrations``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Connection, text

from app.core.logging import log_event
from app.database import models  # noqa: F401  (import registers all tables)
from app.database.base import Base

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Migration:
    id: str
    description: str
    apply: Callable[[Connection], None]


def _m0001_initial(conn: Connection) -> None:
    Base.metadata.create_all(conn)


def _column_exists(conn: Connection, table: str, column: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == column for r in rows)


def _m0002_indexes(conn: Connection) -> None:
    """Indexes that support the hot queries (approval queue, due schedule)."""
    statements = [
        "CREATE INDEX IF NOT EXISTS ix_drafts_status_updated ON drafts (status, updated_at)",
        "CREATE INDEX IF NOT EXISTS ix_sched_status_time ON scheduled_posts (status, scheduled_at)",
        "CREATE INDEX IF NOT EXISTS ix_analytics_post_time "
        "ON analytics_snapshots (published_post_id, collected_at)",
        "CREATE INDEX IF NOT EXISTS ix_ideas_status_score ON ideas (status, final_score)",
        "CREATE INDEX IF NOT EXISTS ix_llm_usage_created ON llm_usage (created_at)",
    ]
    for stmt in statements:
        conn.execute(text(stmt))


def _m0003_notification_deliver_after(conn: Connection) -> None:
    """Hold low-priority notifications until quiet hours end."""
    if not _column_exists(conn, "notifications", "deliver_after"):
        conn.execute(text("ALTER TABLE notifications ADD COLUMN deliver_after DATETIME"))
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_notifications_deliver_after "
            "ON notifications (deliver_after)"
        )
    )


MIGRATIONS: list[Migration] = [
    Migration("0001_initial", "Create initial schema", _m0001_initial),
    Migration("0002_indexes", "Add query-supporting indexes", _m0002_indexes),
    Migration(
        "0003_notification_deliver_after",
        "Add deferred-delivery column for quiet hours",
        _m0003_notification_deliver_after,
    ),
]


def _ensure_migrations_table(conn: Connection) -> None:
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  id TEXT PRIMARY KEY,"
            "  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        )
    )


def applied_migrations(conn: Connection) -> set[str]:
    _ensure_migrations_table(conn)
    return {row[0] for row in conn.execute(text("SELECT id FROM schema_migrations"))}


def run_migrations() -> list[str]:
    """Apply pending migrations. Returns the ids that were applied."""
    from app.database.session import get_engine

    engine = get_engine()
    newly_applied: list[str] = []
    with engine.begin() as conn:
        done = applied_migrations(conn)
        for migration in MIGRATIONS:
            if migration.id in done:
                continue
            migration.apply(conn)
            conn.execute(
                text("INSERT INTO schema_migrations (id) VALUES (:id)"), {"id": migration.id}
            )
            newly_applied.append(migration.id)
            log_event(log, "MIGRATION_APPLIED", migration=migration.id, description=migration.description)
    return newly_applied
