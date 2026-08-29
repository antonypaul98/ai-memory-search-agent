"""Background job worker — fixed implementation."""

from __future__ import annotations

import logging
import threading
import uuid

from app.config import Settings, get_settings
from app.db.job_store_factory import get_job_execution_context, get_job_store
from app.services.event_bus import EventBus
from app.services.ingest_service import IngestService
from app.services.job_queue_transport import get_job_queue_transport

logger = logging.getLogger(__name__)

_WORKER: JobWorker | None = None


def should_start_job_worker(settings: Settings) -> bool:
    """Return whether this process is allowed to execute background jobs."""
    return settings.jobs_enabled and settings.worker_mode in {"worker", "all"}


class JobWorker:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._store = get_job_store(self._settings)
        self._ingest = IngestService(settings=self._settings)
        self._queue = get_job_queue_transport(self._settings)
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
                    self._queue.wait()
                    continue
                job_id, item_key, url = claim
                self._process_item(job_id, item_key, url, worker_id=worker_id)
            except Exception as exc:
                # Queue/provider errors must not destroy durable work. Back off using
                # the polling transport delay before retrying the authoritative store.
                logger.exception("Job worker error: %s", exc)
                self._stop.wait(self._settings.job_poll_interval_sec)

    def _process_item(self, job_id: str, item_key: str, url: str, *, worker_id: str) -> None:
        context = get_job_execution_context(self._settings, job_id)
        user_id = context.user_id
        reflection = context.reflection
        force_refresh = context.force_refresh
        heartbeat_stop = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(job_id, item_key, worker_id, heartbeat_stop),
            name=f"job-heartbeat-{item_key[:12]}",
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            result = self._ingest.ingest_single_url(
                url,
                user_id=user_id,
                reflection=reflection,
                force_refresh=force_refresh,
            )
            if result.skipped:
                item_status = "skipped"
                completed = self._store.complete_item(
                    job_id=job_id,
                    item_key=item_key,
                    status=item_status,
                    worker_id=worker_id,
                )
            elif result.success:
                item_status = "completed"
                completed = self._store.complete_item(
                    job_id=job_id,
                    item_key=item_key,
                    status=item_status,
                    worker_id=worker_id,
                )
            else:
                item_status = "failed"
                completed = self._store.complete_item(
                    job_id=job_id,
                    item_key=item_key,
                    status=item_status,
                    error=result.error or "Unknown error",
                    worker_id=worker_id,
                )
            if not completed:
                logger.warning(
                    "Discarded stale job completion job_id=%s item_key=%s worker_id=%s",
                    job_id,
                    item_key,
                    worker_id,
                )
            else:
                self._emit_worker_state_change(
                    user_id=user_id,
                    job_id=job_id,
                    item_status=item_status,
                )
        except Exception as exc:
            completed = self._store.complete_item(
                job_id=job_id,
                item_key=item_key,
                status="failed",
                error=str(exc),
                worker_id=worker_id,
            )
            if not completed:
                logger.warning(
                    "Discarded stale failed completion job_id=%s item_key=%s worker_id=%s",
                    job_id,
                    item_key,
                    worker_id,
                )
            else:
                self._emit_worker_state_change(
                    user_id=user_id,
                    job_id=job_id,
                    item_status="failed",
                )
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=1.0)

    def _emit_worker_state_change(
        self,
        *,
        user_id: str,
        job_id: str,
        item_status: str,
    ) -> None:
        """Audit authoritative worker completion without content or error details.

        Audit delivery is deliberately isolated from durable job completion. A
        telemetry failure must never cause a successfully finalized item to be
        rewritten as failed or retried.
        """
        try:
            EventBus(self._settings).emit(
                user_id=user_id,
                event_type="job.state_changed",
                aggregate_type="job",
                aggregate_id=job_id,
                actor="worker",
                payload={
                    "action": "item_finalized",
                    "item_status": item_status,
                },
            )
        except Exception:
            logger.exception("Failed to audit worker job transition job_id=%s", job_id)

    def _heartbeat_loop(
        self,
        job_id: str,
        item_key: str,
        worker_id: str,
        stop_event: threading.Event,
    ) -> None:
        """Keep a long-running ingest claim alive; stop immediately after ownership loss."""
        interval = max(0.1, self._settings.job_lease_seconds / 3)
        while not stop_event.wait(interval):
            try:
                if not self._store.heartbeat_item(
                    job_id=job_id,
                    item_key=item_key,
                    worker_id=worker_id,
                ):
                    return
            except Exception as exc:
                # A missed heartbeat must not make a stale worker authoritative. If
                # another worker eventually reclaims the item, complete_item's owner
                # check rejects this worker's late result.
                logger.warning(
                    "Job heartbeat failed job_id=%s item_key=%s worker_id=%s error=%s",
                    job_id,
                    item_key,
                    worker_id,
                    exc,
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
