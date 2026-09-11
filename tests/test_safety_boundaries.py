"""The product's safety promises, asserted against the real code.

These tests exist so a future change cannot quietly turn this into the kind of
automation the project explicitly refuses to be.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "backend" / "app"


def _all_source() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in BACKEND.rglob("*.py")).lower()


def test_no_browser_automation_dependency():
    """No selenium/playwright/puppeteer anywhere in the backend."""
    source = _all_source()
    for banned in ("selenium", "playwright", "puppeteer", "webdriver", "undetected_chromedriver"):
        assert banned not in source, f"browser automation library referenced: {banned}"


def test_no_linkedin_credential_or_cookie_handling():
    """The system never touches a LinkedIn password or session cookie."""
    source = _all_source()
    for banned in ("li_at", "jsessionid", "linkedin_password", "session_cookie"):
        assert banned not in source, f"session/credential hack referenced: {banned}"


def test_networking_module_cannot_send_invitations():
    from app.networking import service

    source = inspect.getsource(service).lower()
    for banned in ("send_invitation", "send_connect", "invite(", "post_invitation", "/invitations"):
        assert banned not in source, f"networking module can send invitations: {banned}"


def test_no_bulk_or_engagement_endpoints():
    """No endpoint performs mass actions, likes, comments or DMs."""
    from app.main import create_app

    paths = " ".join(create_app().openapi()["paths"]).lower()
    for banned in (
        "bulk",
        "mass",
        "/like",
        "/comment",
        "/dm",
        "/message",
        "auto-connect",
        "invite",
    ):
        assert banned not in paths, f"unsafe endpoint exposed: {banned}"


def test_publisher_modes_are_manual_or_official_api_only():
    from app.config import Settings
    from app.linkedin.publisher import LinkedInApiPublisher, ManualPublisher, get_publisher

    assert isinstance(get_publisher(Settings(linkedin_publish_mode="manual")), ManualPublisher)
    assert isinstance(get_publisher(Settings(linkedin_publish_mode="api")), LinkedInApiPublisher)
    # An unrecognised mode must fall back to the *safe* option, never a riskier one.
    assert isinstance(get_publisher(Settings(linkedin_publish_mode="browser")), ManualPublisher)


def test_manual_publisher_never_reports_a_publication():
    from app.linkedin.publisher import ManualPublisher

    result = ManualPublisher().publish("some content", draft_id=1)
    assert result.published is False
    assert result.awaiting_user_action is True
    assert result.copy_ready_content == "some content"


def test_api_publisher_refuses_without_credentials(monkeypatch):
    """It must fail loudly rather than silently degrading."""
    from app.config import Settings
    from app.core.errors import PublishingNotConfiguredError
    from app.linkedin.publisher import LinkedInApiPublisher

    publisher = LinkedInApiPublisher(Settings(linkedin_publish_mode="api"))
    assert publisher.health_check().status == "not_configured"
    with pytest.raises(PublishingNotConfiguredError):
        publisher.publish("content", draft_id=1)


def test_analytics_never_fabricates_missing_metrics(db):
    """A snapshot with nothing collected must not count as zero engagement."""
    from app.analytics.engine import engagement_of
    from app.database.models import AnalyticsSnapshot

    empty = AnalyticsSnapshot(published_post_id=1, collected_at=None, source="manual")
    assert engagement_of(empty) is None

    real = AnalyticsSnapshot(
        published_post_id=1, collected_at=None, source="manual", reactions=10, impressions=1000
    )
    assert engagement_of(real) is not None


def test_learning_engine_refuses_to_generalise_from_tiny_samples(db):
    from app.analytics.engine import compute_insights
    from app.database.enums import ConfidenceLevel

    insights = compute_insights(db)
    assert len(insights) == 1
    assert insights[0].confidence == ConfidenceLevel.INSUFFICIENT_DATA
    assert "at least" in insights[0].statement.lower()


def test_research_prompt_forbids_fabrication():
    from app.agents.research.agent import RESEARCH_SYSTEM

    lowered = RESEARCH_SYSTEM.lower()
    assert "never invent" in lowered
    assert "benchmark" in lowered


def test_writer_prompt_forbids_engagement_bait_and_hype():
    from app.content.prompts import BASE_SYSTEM

    lowered = BASE_SYSTEM.lower()
    assert "never invent" in lowered
    assert "engagement bait" in lowered
    assert "game changer" in lowered


def test_network_discovery_reads_followed_sources_only(db):
    """Candidates come from content the user already follows - not a search."""
    from app.networking.service import extract_candidates_from_text

    found = extract_candidates_from_text(
        "Good writeup from https://www.linkedin.com/in/jane-doe-123/ on queues.",
        context="Mentioned in a feed the user follows",
    )
    assert len(found) == 1
    assert found[0].profile_url.endswith("/in/jane-doe-123")


def test_network_loop_stays_small(db, monkeypatch):
    """No mass activity: the run is capped by the configured limit."""
    from app.core.settings_store import set_setting
    from app.database.models import ConnectionCandidate
    from app.jobs.handlers import discover_connections

    set_setting(db, "network_recommendations_per_run", 3)
    db.commit()

    payload = {
        "scan_sources": False,
        "candidates": [
            {"name": f"Person {i}", "profile_url": f"https://linkedin.com/in/person-{i}"}
            for i in range(25)
        ],
    }
    discover_connections(db, payload)
    db.commit()

    assert db.query(ConnectionCandidate).count() == 3


def test_connection_status_values_never_imply_the_system_acted(db):
    """The terminal state is 'the user says they connected', not 'we connected'."""
    from app.database.enums import ConnectionStatus

    values = {str(v) for v in ConnectionStatus}
    assert "MARKED_CONNECTED" in values
    for forbidden in ("SENT", "INVITED", "REQUESTED", "CONNECTED"):
        assert forbidden not in values, f"status implies the system acted: {forbidden}"


def test_people_discovery_uses_github_not_linkedin():
    """Discovery must never scrape or search LinkedIn programmatically."""
    from app.networking import discovery

    source = inspect.getsource(discovery).lower()
    # The only linkedin.com reference may be the search URL handed to the user.
    assert "api.linkedin.com" not in source
    assert "linkedin.com/search" in source, "expected a user-facing search handoff"
    for banned in ("voyager", "li_at", "invitation", "sendinvite", "connect("):
        assert banned not in source, f"discovery touches LinkedIn actions: {banned}"


def test_discovery_only_links_to_a_search_the_user_clicks():
    from app.networking.discovery import LINKEDIN_SEARCH, DiscoveredPerson, to_candidate

    person = DiscoveredPerson(
        name="Ada Lovelace", handle="ada", bio="AI engineer", company="Analytical",
        profile_url=LINKEDIN_SEARCH.format(query="Ada+Lovelace"),
        evidence="Contributes to x/y on GitHub", linkedin_known=False,
    )
    candidate = to_candidate(person)
    assert candidate.profile_url.startswith("https://www.linkedin.com/search/")
    assert candidate.name == "Ada Lovelace"


def test_a_self_published_linkedin_url_is_preferred_over_a_search():
    from app.networking.discovery import _linkedin_from_profile

    assert _linkedin_from_profile({"blog": "https://linkedin.com/in/ada"}) == "https://linkedin.com/in/ada"
    assert _linkedin_from_profile({"bio": "find me at linkedin.com/in/ada-l"}) == "https://linkedin.com/in/ada-l"
    assert _linkedin_from_profile({"blog": "https://example.com"}) is None
