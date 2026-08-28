"""Runtime safety checks for production storage topology.

F-35 introduces split API/worker roles and Redis wake transport, but durable job
metadata is still SQLite until GAP-02 is complete.  Redis wakeups alone do not
make SQLite safe for horizontally separated writers, so fail closed before
starting a split Redis runtime that could corrupt expectations or produce lock
contention under load.
"""

from __future__ import annotations

from app.config import Settings


class UnsafeRuntimeTopology(RuntimeError):
    """Raised when configured process topology exceeds current storage guarantees."""


def validate_runtime_topology(settings: Settings) -> None:
    """Reject split Redis workers while durable job state is SQLite-backed.

    The current :class:`JobStore` uses SQLite ``BEGIN IMMEDIATE`` for claim
    serialization.  That is a valid single-node boundary, but it is not the
    production horizontal claim store required by F-35/GAP-02.  ``api`` and
    ``worker`` modes imply separate processes; combining those modes with the
    Redis wake transport is therefore blocked until the Postgres job-store
    cutover lands.

    SQLite polling and the historical ``all`` mode remain supported so local
    development and the existing single-node deployment continue to work.
    """

    if not settings.jobs_enabled:
        return

    split_process = settings.worker_mode in {"api", "worker"}
    redis_wake_transport = settings.job_queue_backend == "redis"
    if split_process and redis_wake_transport:
        raise UnsafeRuntimeTopology(
            "Split Redis job workers are not production-safe while durable job "
            "state is SQLite-backed. Complete GAP-02/Postgres job-store cutover "
            "before running WORKER_MODE=api|worker with JOB_QUEUE_BACKEND=redis."
        )
