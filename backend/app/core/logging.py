"""Structured logging.

Every meaningful domain action is emitted as a named event (POST_APPROVED,
DEVICE_PAIRED, ...) so the log can be grepped and, later, shipped somewhere.
Secrets are never passed to these helpers - callers pass identifiers only.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

_SENSITIVE_KEYS = {
    "token", "access_token", "refresh_token", "api_key", "secret",
    "password", "cookie", "authorization", "pairing_code", "token_hash",
}

_configured = False


def _redact(payload: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in payload.items():
        if key.lower() in _SENSITIVE_KEYS:
            clean[key] = "***redacted***"
        elif isinstance(value, dict):
            clean[key] = _redact(value)
        else:
            clean[key] = value
    return clean


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        event = getattr(record, "event", None)
        if event:
            base["event"] = event
        fields = getattr(record, "fields", None)
        if fields:
            base["fields"] = fields
        if record.exc_info:
            base["exc"] = self.formatException(record.exc_info)
        return json.dumps(base, default=str)


def configure_logging(level: str = "INFO", as_json: bool = False) -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    if as_json:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s")
        )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    logging.getLogger("httpx").setLevel(logging.WARNING)
    _configured = True


def log_event(
    logger: logging.Logger,
    event: str,
    /,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Emit a structured domain event.

    ``log_event(log, "POST_APPROVED", draft_id=3, device_id="abc")``
    """
    safe = _redact(fields)
    rendered = " ".join(f"{k}={v}" for k, v in safe.items())
    logger.log(level, "%s %s", event, rendered, extra={"event": event, "fields": safe})
