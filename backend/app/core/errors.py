"""Domain errors that translate into actionable API responses.

The mobile app should never have to show a bare "Error 500". Every error
carries a stable ``code``, a human sentence and, where one exists, a suggested
recovery action the UI can render as a button.
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    code = "internal_error"
    http_status = 500
    message = "Something went wrong."
    recovery: str | None = None

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        http_status: int | None = None,
        recovery: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        if code:
            self.code = code
        if http_status:
            self.http_status = http_status
        if recovery is not None:
            self.recovery = recovery
        self.details = details or {}
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.recovery:
            payload["recovery"] = self.recovery
        if self.details:
            payload["details"] = self.details
        return payload


class NotFoundError(DomainError):
    code = "not_found"
    http_status = 404
    message = "That item no longer exists."
    recovery = "Refresh the list."


class InvalidTransitionError(DomainError):
    code = "invalid_transition"
    http_status = 409
    message = "This post is not in a state where that action is allowed."
    recovery = "Refresh to see the current status."


class ContentChangedError(DomainError):
    code = "content_changed"
    http_status = 409
    message = "The post changed since you loaded it, so the approval was not recorded."
    recovery = "Review the updated version and approve again."


class ApprovalInvalidError(DomainError):
    code = "approval_invalid"
    http_status = 409
    message = "There is no valid approval for the current content."
    recovery = "Approve the post again."


class BudgetExceededError(DomainError):
    code = "budget_exceeded"
    http_status = 429
    message = "The configured AI spending limit for this period has been reached."
    recovery = "Raise the limit in Settings or wait for the next period."


class ProviderUnavailableError(DomainError):
    code = "provider_unavailable"
    http_status = 503
    message = "The AI provider could not be reached."
    recovery = "Check the provider configuration, then retry."


class PublishingNotConfiguredError(DomainError):
    code = "publishing_not_configured"
    http_status = 409
    message = "LinkedIn publishing is not configured."
    recovery = "Finish LinkedIn setup, or keep using manual publishing."


class PublishingAuthExpiredError(DomainError):
    code = "publishing_auth_expired"
    http_status = 401
    message = "The LinkedIn publishing authorisation has expired."
    recovery = "Reconnect LinkedIn in Settings."


class ConflictError(DomainError):
    code = "conflict"
    http_status = 409
    message = "That action conflicts with the current state."


class ValidationError(DomainError):
    code = "validation_error"
    http_status = 422
    message = "The request was not valid."
