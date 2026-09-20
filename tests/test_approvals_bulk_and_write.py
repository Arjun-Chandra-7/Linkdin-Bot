"""Clearing the queue, and writing a post without having to think of a topic.

Two bits of friction on the approvals screen: discarding drafts one at a time, and having to type
a topic before anything could be written.
"""
from __future__ import annotations

import pathlib

APP_JS = pathlib.Path(__file__).resolve().parents[1] / "desktop" / "app.js"


def test_the_screen_offers_a_write_button():
    source = APP_JS.read_text()
    assert "writeNextPost" in source
    assert "Write a post now" in source


def test_a_written_draft_opens_for_review_rather_than_publishing_itself():
    """Nothing publishes without the approval gate, and the button must not look like it does."""
    source = APP_JS.read_text()
    start = source.index("async function writeNextPost")
    body = source[start:start + 700]
    assert "go('draft'" in body
    assert "publish" not in body.lower()


def test_drafts_can_be_selected_and_discarded_together():
    source = APP_JS.read_text()
    assert "draft-pick" in source and "toggleSelected" in source
    assert "/api/v1/approvals/discard" in source


def test_ticking_a_box_does_not_also_open_the_draft():
    """The card opens it on click; the checkbox sits inside the card."""
    source = APP_JS.read_text()
    assert "event.stopPropagation()" in source


def test_a_selection_cannot_outlive_the_list_it_was_made_against():
    """Redrawing the queue must reset it, or a stale id discards the wrong draft."""
    source = APP_JS.read_text()
    start = source.index("async function viewApprovals")
    assert "SELECTED = new Set();" in source[start:start + 400]


def test_discarding_asks_first():
    source = APP_JS.read_text()
    start = source.index("async function discardSelected")
    assert "confirm(" in source[start:start + 500]


def test_the_discard_route_does_not_read_as_a_mass_linkedin_action():
    """A safety test refuses any path suggesting mass action, because mass action against
    LinkedIn is what gets an account restricted. This one only throws away local drafts."""
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
    from app.main import create_app

    paths = " ".join(create_app().openapi()["paths"]).lower()
    assert "/api/v1/approvals/discard" in paths
    for banned in ("bulk", "mass", "invite"):
        assert banned not in paths


def test_writing_on_demand_needs_no_topic():
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
    from app.main import create_app

    spec = create_app().openapi()
    post = spec["paths"]["/api/v1/drafts/write-next"]["post"]
    assert "requestBody" not in post, "the point is that it asks for nothing"
