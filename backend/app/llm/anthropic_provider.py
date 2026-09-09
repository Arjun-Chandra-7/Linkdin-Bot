"""Claude provider, via the official Anthropic Python SDK."""

from __future__ import annotations

import logging
from typing import TypeVar

from pydantic import BaseModel

from app.config import Settings
from app.core.errors import DomainError, ProviderUnavailableError
from app.llm.base import LLMProvider, LLMResponse, ProviderStatus
from app.llm.pricing import estimate_cost

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class ContentRefusedError(DomainError):
    code = "content_refused"
    http_status = 422
    message = "The model declined to generate this content."
    recovery = "Try a different topic or rephrase the idea."


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.anthropic_api_key
        self.model = settings.anthropic_model
        self.timeout = settings.llm_timeout_seconds
        self._client = None

    def _get_client(self):
        if not self.api_key:
            raise ProviderUnavailableError(
                "No Anthropic API key is configured.",
                code="provider_not_configured",
                recovery="Set ANTHROPIC_API_KEY in .env, or switch LLM_PROVIDER to mock.",
            )
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout)
        return self._client

    def _usage(self, response) -> tuple[int, int]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return 0, 0
        return int(getattr(usage, "input_tokens", 0)), int(getattr(usage, "output_tokens", 0))

    def _check_refusal(self, response) -> None:
        # Claude may decline (HTTP 200 with stop_reason "refusal"), so the
        # stop reason has to be inspected before reading content.
        if getattr(response, "stop_reason", None) == "refusal":
            details = getattr(response, "stop_details", None)
            raise ContentRefusedError(
                "The model declined to write this post.",
                details={"category": getattr(details, "category", None)},
            )

    def _kwargs(self, effort: str | None) -> dict:
        # Thinking is on by default for Opus 5; effort is the cost/depth dial.
        return {"output_config": {"effort": effort}} if effort else {}

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 2000,
        task: str = "generic",
        effort: str | None = None,
    ) -> LLMResponse:
        client = self._get_client()
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system or "",
                messages=[{"role": "user", "content": prompt}],
                **self._kwargs(effort),
            )
        except DomainError:
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced as a domain error
            raise ProviderUnavailableError(
                f"Claude request failed: {type(exc).__name__}", details={"task": task}
            ) from exc

        self._check_refusal(response)
        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
        prompt_tokens, completion_tokens = self._usage(response)
        return LLMResponse(
            text=text,
            model=self.model,
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=estimate_cost(self.model, prompt_tokens, completion_tokens),
            stop_reason=getattr(response, "stop_reason", None),
        )

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
        client = self._get_client()
        try:
            response = client.messages.parse(
                model=self.model,
                max_tokens=max_tokens,
                system=system or "",
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
                **self._kwargs(effort),
            )
        except DomainError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailableError(
                f"Claude structured request failed: {type(exc).__name__}", details={"task": task}
            ) from exc

        self._check_refusal(response)
        prompt_tokens, completion_tokens = self._usage(response)
        parsed = getattr(response, "parsed_output", None)
        return LLMResponse(
            text=parsed.model_dump_json() if parsed is not None else "",
            model=self.model,
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=estimate_cost(self.model, prompt_tokens, completion_tokens),
            stop_reason=getattr(response, "stop_reason", None),
            parsed=parsed,
        )

    def health_check(self) -> ProviderStatus:
        if not self.api_key:
            return ProviderStatus(
                status="not_configured",
                detail="ANTHROPIC_API_KEY is not set.",
                extra={"model": self.model},
            )
        return ProviderStatus(
            status="ok", detail=f"Claude configured ({self.model}).", extra={"model": self.model}
        )
