"""Runtime safety checks for production storage topology.

F-35 supports split API/worker roles with Redis wake transport only when durable
job state is Postgres-backed. Redis wakeups never become the source of truth;
SQLite remains a single-node boundary and is rejected for split Redis runtimes.
"""

from __future__ import annotations

from app.config import Settings


class UnsafeRuntimeTopology(RuntimeError):
    """Raised when configured process topology exceeds current storage guarantees."""


def validate_runtime_topology(settings: Settings) -> None:
    """Allow split Redis workers only with the validated Postgres durable store.

    SQLite ``JobStore`` uses ``BEGIN IMMEDIATE`` for claim serialization. That is
    a valid single-node boundary but not the horizontal claim store required by
    F-35/GAP-02. Postgres uses atomic row claims/leases and is exercised against
    a real PostgreSQL service in CI. Therefore ``api``/``worker`` + Redis is
    permitted only when ``JOB_STORE_BACKEND=postgres``.

    SQLite polling and historical ``all`` mode remain supported for local and
    single-node deployments.
    """

    if not settings.jobs_enabled:
        return

    split_process = settings.worker_mode in {"api", "worker"}
    redis_wake_transport = settings.job_queue_backend == "redis"
    sqlite_durable_store = settings.job_store_backend == "sqlite"
    if split_process and redis_wake_transport and sqlite_durable_store:
        raise UnsafeRuntimeTopology(
            "Split Redis job workers require the Postgres durable job store. "
            "SQLite job state is single-node only; set JOB_STORE_BACKEND=postgres "
            "after configuring and validating the Postgres runtime."
        )
