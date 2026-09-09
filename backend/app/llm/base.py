"""Provider-agnostic LLM interface.

Nothing above this layer knows which vendor is in use. Adding a provider means
implementing three methods, not touching the agents.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass
class ProviderStatus:
    status: str  # ok | not_configured | error
    detail: str
    extra: dict = field(default_factory=dict)


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    stop_reason: str | None = None
    parsed: BaseModel | None = None


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 2000,
        task: str = "generic",
        effort: str | None = None,
    ) -> LLMResponse:
        """Free-form text generation."""

    @abstractmethod
    def structured_generate(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        max_tokens: int = 2000,
        task: str = "generic",
        effort: str | None = None,
    ) -> LLMResponse:
        """Generation validated against a Pydantic schema."""

    @abstractmethod
    def health_check(self) -> ProviderStatus:
        """Report configuration state without spending tokens."""
