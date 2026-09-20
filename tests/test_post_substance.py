"""Posts must be long enough, and carry something the reader did not already know.

The complaint that prompted this: the generated posts were three short bullet points of things
any engineer in the feed already believes.
"""
from __future__ import annotations

from app.content.prompts import BASE_SYSTEM, FORMAT_GUIDANCE, build_writer_prompt
from app.database.enums import PostType


def test_the_writer_is_told_the_reader_must_learn_something():
    """A post that only lists what everyone already believes has failed, however cleanly it is
    written. That has to be said, because it is not implied by the rest of the rules."""
    assert "did not know before" in BASE_SYSTEM
    assert "Three bullet points is not a post" in BASE_SYSTEM


def test_the_kinds_of_substance_are_named_rather_than_left_to_taste():
    for demand in ("mechanism", "number", "constraint", "trade-off"):
        assert demand in BASE_SYSTEM.lower()


def test_the_default_length_can_hold_an_argument():
    prompt = build_writer_prompt(topic="anything", post_type=PostType.TECHNICAL_BREAKDOWN)
    assert "1600-2800 characters" in prompt


def test_length_is_to_be_reached_with_substance_not_padding():
    """Otherwise a longer target just buys longer generalities."""
    prompt = build_writer_prompt(topic="anything", post_type=PostType.OPINION)
    assert "never by restating" in prompt
    assert "write less and say so" in prompt


def test_a_short_observation_stays_short():
    """It is short on purpose. Stretched to two thousand characters it is no longer one."""
    prompt = build_writer_prompt(topic="anything", post_type=PostType.SHORT_OBSERVATION,
                                 target_range=(1600, 2800))
    assert "350-700 characters" in prompt
    assert "1600-2800" not in prompt


def test_an_explicit_range_is_still_honoured_for_ordinary_posts():
    prompt = build_writer_prompt(topic="anything", post_type=PostType.BUILD_LOG,
                                 target_range=(900, 1100))
    assert "900-1100 characters" in prompt


def test_news_must_say_what_the_announcement_does_not():
    """The headline is already in everyone's feed; repeating it adds nothing."""
    guidance = FORMAT_GUIDANCE[PostType.NEWS_WITH_ANALYSIS]
    assert "not in the announcement" in guidance
    assert "release notes leave out" in guidance
    assert "changes little" in guidance          # a sober take is allowed to be the take


def test_the_anti_hype_rules_survived():
    """The new demands must not have loosened the old restraint."""
    for banned in ("game changer", "engagement bait", "Never invent numbers"):
        assert banned in BASE_SYSTEM


def test_history_of_short_posts_cannot_drag_the_target_below_a_usable_length():
    """Learning length from what was published is a loop that only tightens: a run of short
    posts teaches "short", which produces shorter posts, which teach shorter still. Nothing in
    the history pushes back, because a post that was never written cannot be measured."""
    from app.agents.writer.style import FLOOR

    assert FLOOR[0] >= 1000 and FLOOR[1] > FLOOR[0]
