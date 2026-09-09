"""Spend tracking and budget enforcement."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BudgetExceededError
from app.core.logging import log_event
from app.core.settings_store import get_setting
from app.database.base import utcnow
from app.database.models import LLMUsage
from app.llm.base import LLMResponse

log = logging.getLogger(__name__)


def spend_since(db: Session, since) -> float:
    total = db.execute(
        select(func.coalesce(func.sum(LLMUsage.estimated_cost_usd), 0.0)).where(
            LLMUsage.created_at >= since
        )
    ).scalar_one()
    return float(total or 0.0)


def current_spend(db: Session) -> dict[str, float]:
    now = utcnow()
    return {
        "day": spend_since(db, now - timedelta(days=1)),
        "month": spend_since(db, now - timedelta(days=30)),
    }


def assert_within_budget(db: Session) -> None:
    """Raise before making a call that would exceed the configured limits."""
    spend = current_spend(db)
    daily_limit = float(get_setting(db, "llm_daily_cost_limit_usd"))
    monthly_limit = float(get_setting(db, "llm_monthly_cost_limit_usd"))

    if daily_limit > 0 and spend["day"] >= daily_limit:
        raise BudgetExceededError(
            f"Daily AI budget of ${daily_limit:.2f} is used up (${spend['day']:.2f} spent).",
            details={"period": "day", "spent": round(spend["day"], 4), "limit": daily_limit},
        )
    if monthly_limit > 0 and spend["month"] >= monthly_limit:
        raise BudgetExceededError(
            f"Monthly AI budget of ${monthly_limit:.2f} is used up (${spend['month']:.2f} spent).",
            details={"period": "month", "spent": round(spend["month"], 4), "limit": monthly_limit},
        )


def record_usage(db: Session, response: LLMResponse, task: str, succeeded: bool = True) -> LLMUsage:
    usage = LLMUsage(
        provider=response.provider,
        model=response.model,
        task=task,
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
        estimated_cost_usd=response.estimated_cost_usd,
        succeeded=succeeded,
    )
    db.add(usage)
    db.flush()
    if response.estimated_cost_usd:
        log_event(
            log,
            "LLM_CALL",
            task=task,
            model=response.model,
            tokens=response.prompt_tokens + response.completion_tokens,
            cost_usd=round(response.estimated_cost_usd, 5),
        )
    return usage
