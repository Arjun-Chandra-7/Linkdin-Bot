"""Runtime settings, editable from the mobile Settings screen.

These are stored in the database (not .env) because the user changes them at
runtime: posting cadence, category mix, thresholds, cost limits.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Setting

DEFAULTS: dict[str, Any] = {
    # --- Scheduling ---
    "timezone": "Asia/Kolkata",
    # Local wall-clock slots. Nothing is hard-coded to specific days elsewhere.
    "posting_slots": [
        {"weekday": "MON", "time": "10:00"},
        {"weekday": "WED", "time": "14:00"},
        {"weekday": "FRI", "time": "11:30"},
    ],
    "max_posts_per_week": 3,
    "min_hours_between_posts": 20,
    # --- Content mix (fractions, normalised on read) ---
    "category_mix": {
        "BUILD_LOG": 0.40,
        "TECHNICAL_LESSON": 0.25,
        "AI_OBSERVATION": 0.20,
        "MILESTONE": 0.15,
    },
    # --- Pipeline thresholds ---
    "idea_score_threshold": 0.55,
    "quality_threshold": 70,
    "ai_slop_max_probability": 0.35,
    "max_ideas_per_run": 12,
    "max_research_per_run": 5,
    "max_drafts_per_run": 3,
    "multi_variant_threshold": 0.75,  # only strong ideas get A/B/C variants
    "duplicate_similarity_threshold": 0.82,
    # --- Cost control ---
    "llm_daily_cost_limit_usd": 2.0,
    "llm_monthly_cost_limit_usd": 25.0,
    # --- Networking ---
    "network_recommendations_per_run": 5,
    "network_run_interval_hours": 72,
    # --- Discovery / analytics cadence ---
    "discovery_interval_hours": 24,
    "discovery_hour_local": 8,
    "analytics_interval_hours": 12,
    # --- Notifications ---
    "notifications_enabled": True,
    "batch_low_priority_notifications": True,
    "quiet_hours": {"start": "22:30", "end": "07:30"},
    # --- Writing preferences (seeded, then refined by the learning engine) ---
    "preferred_length_range": [700, 1400],
    "banned_phrases": [],
}


def get_setting(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(Setting, key)
    if row is None:
        return DEFAULTS.get(key, default)
    return row.value


def set_setting(session: Session, key: str, value: Any) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value


def all_settings(session: Session) -> dict[str, Any]:
    """Defaults overlaid with any stored overrides."""
    merged = dict(DEFAULTS)
    for row in session.execute(select(Setting)).scalars():
        merged[row.key] = row.value
    return merged


def update_settings(session: Session, updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if key not in DEFAULTS:
            raise KeyError(f"Unknown setting: {key}")
        set_setting(session, key, value)
    session.flush()
    return all_settings(session)
