from datetime import timedelta

from app.api.v1.system import system_status
from app.config import get_settings
from app.database.base import utcnow


def test_linkedin_status_warns_before_member_token_expires(db, monkeypatch):
    monkeypatch.setenv("LINKEDIN_PUBLISH_MODE", "api")
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "member-token")
    monkeypatch.setenv("LINKEDIN_AUTHOR_URN", "urn:li:person:test")
    monkeypatch.setenv(
        "LINKEDIN_TOKEN_ISSUED_AT", (utcnow() - timedelta(days=54)).isoformat()
    )
    get_settings.cache_clear()

    status = system_status(db=db, _=None)

    assert status.linkedin.status == "degraded"
    assert "Reconnect LinkedIn" in status.linkedin.detail
