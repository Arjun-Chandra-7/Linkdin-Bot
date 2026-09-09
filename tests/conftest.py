"""Shared test fixtures.

Each test gets a throwaway SQLite file so migrations, WAL and foreign keys
behave exactly as they do in production.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("SECRET_KEY", "test-secret-not-used-in-production")
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    from app.config import get_settings
    from app.database.migrations import run_migrations
    from app.database.session import get_session_factory, reset_engine_for_tests

    get_settings.cache_clear()
    reset_engine_for_tests()
    run_migrations()

    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
        reset_engine_for_tests()
        get_settings.cache_clear()


@pytest.fixture()
def make_draft(db):
    """Factory producing a draft sitting in READY_FOR_REVIEW with one version."""
    from app.approvals.service import add_version
    from app.database.enums import ContentCategory, DraftStatus, PostType
    from app.database.models import Draft

    def _make(
        content: str = "I shipped the approval flow today.\n\nIt broke twice before it worked.",
        status: DraftStatus = DraftStatus.READY_FOR_REVIEW,
    ) -> Draft:
        draft = Draft(
            title="Approval flow build log",
            post_type=PostType.BUILD_LOG,
            category=ContentCategory.BUILD_LOG,
            status=status,
        )
        db.add(draft)
        db.flush()
        add_version(db, draft, content)
        db.commit()
        return draft

    return _make
