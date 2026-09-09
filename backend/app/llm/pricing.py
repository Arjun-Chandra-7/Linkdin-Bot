"""Token pricing, used to estimate spend and enforce budgets.

USD per million tokens. These are list prices and change over time - they are
only used for local budget guardrails, never billed against.
"""

from __future__ import annotations

MODEL_PRICING: dict[str, tuple[float, float]] = {
    # model id -> (input $/MTok, output $/MTok)
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}

_FALLBACK = (3.00, 15.00)


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Cost estimate in USD. Unknown models use a mid-range assumption."""
    price_in, price_out = MODEL_PRICING.get(model, _FALLBACK)
    return (prompt_tokens / 1_000_000) * price_in + (completion_tokens / 1_000_000) * price_out
