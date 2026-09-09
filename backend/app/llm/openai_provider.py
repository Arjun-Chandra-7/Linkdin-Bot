"""OpenAI-compatible provider.

Kept deliberately thin: it targets the ``/chat/completions`` shape that most
OpenAI-compatible endpoints (OpenAI, local servers, gateways) implement, so a
different model can be swapped in without touching the agents.
"""

from __future__ import annotations

import json
import logging
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.core.errors import ProviderUnavailableError
from app.llm.base import LLMProvider, LLMResponse, ProviderStatus
from app.llm.pricing import estimate_cost

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class OpenAICompatibleProvider(LLMProvider):
    name = "openai"

    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.openai_api_key
        self.base_url = settings.openai_base_url.rstrip("/")
        self.model = settings.openai_model
        self.timeout = settings.llm_timeout_seconds

    def _post(self, payload: dict, task: str) -> dict:
        if not self.api_key:
            raise ProviderUnavailableError(
                "No OpenAI API key is configured.",
                code="provider_not_configured",
                recovery="Set OPENAI_API_KEY in .env, or switch LLM_PROVIDER to mock.",
            )
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(
                f"Could not reach the model endpoint: {type(exc).__name__}",
                details={"task": task},
            ) from exc

        if response.status_code >= 400:
            raise ProviderUnavailableError(
                f"Model endpoint returned {response.status_code}.",
                details={"task": task, "body": response.text[:200]},
            )
        return response.json()

    def _to_response(self, data: dict, parsed: BaseModel | None = None) -> LLMResponse:
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        choice = (data.get("choices") or [{}])[0]
        return LLMResponse(
            text=(choice.get("message") or {}).get("content") or "",
            model=self.model,
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=estimate_cost(self.model, prompt_tokens, completion_tokens),
            stop_reason=choice.get("finish_reason"),
            parsed=parsed,
        )

    def _messages(self, prompt: str, system: str | None) -> list[dict]:
        messages = [{"role": "user", "content": prompt}]
        if system:
            messages.insert(0, {"role": "system", "content": system})
        return messages

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 2000,
        task: str = "generic",
        effort: str | None = None,
    ) -> LLMResponse:
        data = self._post(
            {
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": self._messages(prompt, system),
            },
            task,
        )
        return self._to_response(data)

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
        data = self._post(
            {
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": self._messages(prompt, system),
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema.__name__,
                        "schema": schema.model_json_schema(),
                        "strict": False,
                    },
                },
            },
            task,
        )
        response = self._to_response(data)
        try:
            response.parsed = schema.model_validate(json.loads(response.text))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ProviderUnavailableError(
                "The model returned output that did not match the expected schema.",
                details={"task": task, "error": str(exc)[:200]},
            ) from exc
        return response

    def health_check(self) -> ProviderStatus:
        if not self.api_key:
            return ProviderStatus(status="not_configured", detail="OPENAI_API_KEY is not set.")
        return ProviderStatus(
            status="ok", detail=f"OpenAI-compatible endpoint configured ({self.model}).",
            extra={"model": self.model, "base_url": self.base_url},
        )
