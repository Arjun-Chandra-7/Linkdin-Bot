"""Provider selection and the metered wrapper used by every agent."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import LLMProvider, LLMResponse, ProviderStatus
from app.llm.mock import MockProvider
from app.llm.openai_provider import OpenAICompatibleProvider

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


def build_provider(settings: Settings) -> LLMProvider:
    provider = (settings.llm_provider or "mock").lower()
    if provider == "anthropic":
        return AnthropicProvider(settings)
    if provider == "openai":
        return OpenAICompatibleProvider(settings)
    if provider != "mock":
        log.warning("Unknown LLM_PROVIDER=%r; using the offline mock provider", provider)
    return MockProvider()


@lru_cache
def get_provider() -> LLMProvider:
    return build_provider(get_settings())


class MeteredLLM:
    """Budget check before the call, usage recorded after it.

    Agents use this rather than the raw provider so every token is accounted
    for and a runaway loop hits the configured ceiling instead of the wallet.
    """

    def __init__(self, db: Session, provider: LLMProvider | None = None) -> None:
        self.db = db
        self.provider = provider or get_provider()

    def generate(self, prompt: str, *, task: str, **kwargs) -> LLMResponse:
        from app.llm.budget import assert_within_budget, record_usage

        assert_within_budget(self.db)
        response = self.provider.generate(prompt, task=task, **kwargs)
        record_usage(self.db, response, task)
        return response

    def structured(self, prompt: str, schema: type[T], *, task: str, **kwargs) -> T:
        from app.llm.budget import assert_within_budget, record_usage

        assert_within_budget(self.db)
        response = self.provider.structured_generate(prompt, schema, task=task, **kwargs)
        record_usage(self.db, response, task)
        if response.parsed is None:
            raise ValueError(f"Provider returned no structured output for task {task}")
        return response.parsed  # type: ignore[return-value]

    def health_check(self) -> ProviderStatus:
        return self.provider.health_check()
