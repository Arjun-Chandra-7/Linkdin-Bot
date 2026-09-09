"""Job handler registry."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

JobHandler = Callable[[Session, dict[str, Any]], dict[str, Any] | None]
HANDLERS: dict[str, JobHandler] = {}


def job_handler(name: str) -> Callable[[JobHandler], JobHandler]:
    def decorator(fn: JobHandler) -> JobHandler:
        HANDLERS[name] = fn
        return fn

    return decorator


def get_handler(name: str) -> JobHandler | None:
    return HANDLERS.get(name)
