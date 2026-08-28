"""Background job worker — fixed implementation."""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid

from app.config import Settings, get_settings
from app.db.job_store import JobStore
from app.db.schema import get_connection, migrate
from app.models.reflection import ReflectionInput
from app.services.ingest_service import IngestService

logger = logging.getLogger(__name__)

_WORKER: JobWorker | None = None


def should_start_job_worker(settings: Settings) -> bool:
    """Return whether this process is allowed to execute background jobs."""
    return settings.jobs_enabled and settings.worker_mode in {"worker", "all"}


class JobWorker:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._store = JobStore(self._settings)
        self._ingest = IngestService(settings=self._settings)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        if not should_start_job_worker(self._settings):
            return
        for idx in range(self._settings.job_worker_concurrency):
            thread = threading.Thread(target=self._loop, name=f"job-worker-{idx}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        worker_id = f"worker-{uuid.uuid4().hex[:8]}"
        while not self._stop.is_set():
            try:
                claim = self._store.claim_next_item(worker_id=worker_id)
                if not claim:
                    time.sleep(self._settings.job_poll_interval_sec)
                    continue
                job_id, item_key, url = claim
                self._process_item(job_id, item_key, url)
            except Exception as exc:
                logger.exception("Job worker error: %s", exc)
                time.sleep(self._settings.job_poll_interval_sec)

    def _process_item(self, job_id: str, item_key: str, url: str) -> None:
        user_id = _job_user(self._settings, job_id)
        reflection = _job_reflection(self._settings, job_id)
        force_refresh = _job_force_refresh(self._settings, job_id)
        try:
            result = self._ingest.ingest_single_url(
                url,
                user_id=user_id,
                reflection=reflection,
                force_refresh=force_refresh,
            )
            if result.skipped:
                self._store.complete_item(job_id=job_id, item_key=item_key, status="skipped")
            elif result.success:
                self._store.complete_item(job_id=job_id, item_key=item_key, status="completed")
            else:
                self._store.complete_item(
                    job_id=job_id,
                    item_key=item_key,
                    status="failed",
                    error=result.error or "Unknown error",
                )
        except Exception as exc:
            self._store.complete_item(
                job_id=job_id,
                item_key=item_key,
                status="failed",
                error=str(exc),
            )


def start_job_worker(settings: Settings | None = None) -> JobWorker:
    global _WORKER
    settings = settings or get_settings()
    if _WORKER is None:
        _WORKER = JobWorker(settings)
        _WORKER.start()
    return _WORKER


def stop_job_worker() -> None:
    global _WORKER
    if _WORKER is not None:
        _WORKER.stop()
        for thread in _WORKER._threads:
            thread.join(timeout=2.0)
        _WORKER = None


def _job_user(settings: Settings, job_id: str) -> str:
    migrate(settings)
    with get_connection(settings) as conn:
        row = conn.execute(
            "SELECT user_id FROM background_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    return row["user_id"] if row else "local-default"


def _job_reflection(settings: Settings, job_id: str) -> ReflectionInput | None:
    migrate(settings)
    with get_connection(settings) as conn:
        row = conn.execute(
            "SELECT reflection_json FROM background_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    if not row or not row["reflection_json"]:
        return None
    try:
        return ReflectionInput.model_validate(json.loads(row["reflection_json"]))
    except Exception:
        return None


def _job_force_refresh(settings: Settings, job_id: str) -> bool:
    migrate(settings)
    with get_connection(settings) as conn:
        row = conn.execute(
            "SELECT force_refresh FROM background_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    return bool(row and row["force_refresh"])