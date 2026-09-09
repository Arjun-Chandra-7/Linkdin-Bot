"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.errors import DomainError
from app.core.logging import configure_logging, log_event
from app.database.migrations import run_migrations
from app.jobs import handlers as _handlers  # noqa: F401  (registers job handlers)
from app.jobs.worker import JobWorker

log = logging.getLogger(__name__)

API_PREFIX = "/api/v1"


def _check_secret(settings) -> None:
    """Refuse to run a LAN-exposed server with the shipped default secret."""
    if settings.secret_key.startswith("dev-only") and settings.is_production:
        if not settings.allow_insecure_secret:
            raise RuntimeError(
                "SECRET_KEY is still the default. Generate one before running in production."
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    _check_secret(settings)

    applied = run_migrations()
    if applied:
        log_event(log, "SCHEMA_MIGRATED", migrations=",".join(applied))

    worker: JobWorker | None = None
    if settings.scheduler_enabled:
        worker = JobWorker(tick_seconds=settings.job_tick_seconds)
        worker.start()
    app.state.worker = worker

    log_event(log, "BACKEND_STARTED", env=settings.app_env, port=settings.port)
    try:
        yield
    finally:
        if worker is not None:
            worker.stop()
        log_event(log, "BACKEND_STOPPED")


def create_app() -> FastAPI:
    app = FastAPI(
        title="LinkedIn Content Copilot",
        description=(
            "Personal LinkedIn content system: discovery, drafting, quality gating, "
            "human approval from an Android app, scheduling, publishing and learning."
        ),
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    @app.exception_handler(DomainError)
    async def _domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Keep one error shape across the API so the app never has to parse
        # FastAPI's raw validation format to show a usable message.
        first = (exc.errors() or [{}])[0]
        field = ".".join(str(part) for part in first.get("loc", [])[1:]) or "request"
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": f"{field}: {first.get('msg', 'is not valid')}",
                "recovery": "Check the request and try again.",
            },
        )

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            return JSONResponse(status_code=exc.status_code, content=detail, headers=exc.headers)
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": f"http_{exc.status_code}", "message": str(detail)},
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
        # Never leak a stack trace or a bare "Error 500" to the phone.
        log.exception("Unhandled error")
        return JSONResponse(
            status_code=500,
            content={
                "code": "internal_error",
                "message": "The backend hit an unexpected error.",
                "recovery": "Check the backend logs, then retry.",
            },
        )

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        """Unauthenticated liveness probe. Deliberately reveals nothing."""
        return {"status": "ok", "service": "linkedin-copilot"}

    from app.api.v1 import (
        analytics,
        approvals,
        auth,
        drafts,
        network,
        notifications,
        schedule,
        settings as settings_router,
        system,
    )

    for module in (
        auth,
        drafts,
        approvals,
        schedule,
        network,
        analytics,
        notifications,
        settings_router,
        system,
    ):
        app.include_router(module.router, prefix=API_PREFIX)

    return app


app = create_app()
