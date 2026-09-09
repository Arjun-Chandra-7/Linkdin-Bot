"""The quality gate must reject AI slop before it ever reaches the phone."""

from __future__ import annotations

import pytest
from app.agents.quality.detector import APPROVE, REJECT, analyze, passes_gate

SLOP = """AI isn't coming.
It's already here.

Here are 7 things you MUST know:

1. It's a game changer
2. It's revolutionary
3. Mind-blowing 10x results 🚀🚀🔥

Agree?

#ai #tech #innovation #motivation"""

REAL_BUILD_LOG = """I spent three days making the job queue survive a laptop restart.

The bug: jobs left in RUNNING state after a crash were never retried, so a post
scheduled for Wednesday silently never went out. SQLite defaults did not help
either - the writer was blocking readers until I turned on WAL.

Two changes fixed it. On boot, any job still marked RUNNING gets requeued.
Retries use exponential backoff capped at an hour, and every job carries an
idempotency key so a redelivered job publishes once.

The part I got wrong initially: I stored the approval against a version id
instead of a content hash, which meant a no-op regeneration invalidated
consent for identical text."""

BLAND = """Artificial intelligence is transforming the way businesses operate today.

Companies that adopt these tools will see significant benefits in productivity
and efficiency. It is important to stay informed about the latest developments.

The future belongs to those who adapt."""

BAIT = """Automation saved me time this quarter.

Comment below if you agree, and repost this if it helped.
Follow me for more daily tips."""


def test_slop_is_rejected():
    report = analyze(SLOP)
    assert report.recommendation == REJECT
    assert report.ai_slop_probability > 0.6
    assert not passes_gate(report, min_quality=70, max_slop=0.35)


def test_real_build_log_is_approved():
    report = analyze(REAL_BUILD_LOG)
    assert report.recommendation == APPROVE
    assert report.ai_slop_probability < 0.2
    assert passes_gate(report, min_quality=70, max_slop=0.35)


def test_bland_generic_post_does_not_reach_the_phone():
    """No obvious slop markers, but nothing specific either."""
    report = analyze(BLAND)
    assert report.specificity < 45
    assert not passes_gate(report, min_quality=70, max_slop=0.35)


def test_engagement_bait_is_penalised():
    report = analyze(BAIT)
    assert report.engagement_bait_probability >= 0.6
    assert not passes_gate(report, min_quality=70, max_slop=0.35)


def test_scoring_is_deterministic():
    assert analyze(REAL_BUILD_LOG).to_dict() == analyze(REAL_BUILD_LOG).to_dict()


@pytest.mark.parametrize(
    "phrase", ["game changer", "revolutionary", "mind-blowing", "let that sink in"]
)
def test_cliches_are_flagged(phrase):
    report = analyze(f"{REAL_BUILD_LOG}\n\nThis was a {phrase} for the project.")
    assert any(phrase in issue.lower() for issue in report.issues)


def test_emoji_spam_raises_slop_probability():
    clean = analyze(REAL_BUILD_LOG)
    spammed = analyze(REAL_BUILD_LOG + "\n\n🚀🚀🔥💡✨🎯🙌💪🔥🚀 " * 4)
    assert spammed.ai_slop_probability > clean.ai_slop_probability
