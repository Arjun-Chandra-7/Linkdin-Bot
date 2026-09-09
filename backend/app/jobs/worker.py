"""Background worker loop.

A single daemon thread ticks the queue. Keeping it in-process avoids requiring
Redis/Celery for a personal tool, while durability still comes from the
database rather than from process memory.
"""

from __future__ import annotations

import logging
import threading
import uuid

from app.core.logging import log_event
from app.database.session import session_scope
from app.jobs.queue import claim_due_jobs, complete_job, fail_job, recover_orphaned_jobs
from app.jobs.registry import get_handler

log = logging.getLogger(__name__)


class JobWorker:
    def __init__(self, tick_seconds: int = 20, batch: int = 5) -> None:
        self.tick_seconds = tick_seconds
        self.batch = batch
        self.worker_id = f"worker-{uuid.uuid4().hex[:8]}"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        with session_scope() as db:
            recover_orphaned_jobs(db)
        self._thread = threading.Thread(target=self._run, name="job-worker", daemon=True)
        self._thread.start()
        log_event(log, "WORKER_STARTED", worker_id=self.worker_id, tick_seconds=self.tick_seconds)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        log_event(log, "WORKER_STOPPED", worker_id=self.worker_id)

    # -- execution ---------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # pragma: no cover - the loop must never die
                log.exception("Job worker tick failed")
            self._stop.wait(self.tick_seconds)

    def tick(self) -> int:
        """Run one batch of due jobs. Returns how many were executed."""
        with session_scope() as db:
            jobs = claim_due_jobs(db, self.worker_id, limit=self.batch)

        executed = 0
        for job in jobs:
            handler = get_handler(job.type)
            with session_scope() as db:
                fresh = db.get(type(job), job.id)
                if fresh is None:
                    continue
                if handler is None:
                    fail_job(db, fresh, f"No handler registered for job type '{job.type}'")
                    continue
                try:
                    result = handler(db, fresh.payload or {})
                    complete_job(db, fresh, result)
                    executed += 1
                except Exception as exc:  # noqa: BLE001 - recorded and retried
                    log.exception("Job %s (%s) failed", fresh.id, fresh.type)
                    fail_job(db, fresh, f"{type(exc).__name__}: {exc}")
        return executed
