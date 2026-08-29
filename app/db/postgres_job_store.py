"""Application-facing Postgres job-store facade.

This composes the already-validated Postgres repository, worker-claim, control,
and mutation primitives behind the same public behavior used by the SQLite
``JobStore``.  It intentionally does not select Postgres at runtime yet; config,
connection/schema wiring, and end-to-end validation remain separate cutover
steps so the SQLite safety gate stays closed until the backend is truly ready.
"""

from __future__ import annotations

from typing import Any

from app.core.exceptions import AppError
from app.db.postgres_job_claims import PostgresJobClaimStore
from app.db.postgres_job_controls import PostgresJobControlStore
from app.db.postgres_job_mutations import PostgresJobMutationStore
from app.db.postgres_job_repository import ConnectionFactory, PostgresJobRepository
from app.models.job import BackgroundJob, JobDetailResponse
from app.models.reflection import ReflectionInput
from app.services.playlist_service import PlaylistVideoEntry


class PostgresJobStore:
    """Facade matching the durable job operations consumed by API/workers."""

    def __init__(self, connection_factory: ConnectionFactory, *, lease_seconds: int = 120) -> None:
        self._repository = PostgresJobRepository(connection_factory)
        self._claims = PostgresJobClaimStore(connection_factory, lease_seconds=lease_seconds)
        self._controls = PostgresJobControlStore(connection_factory)
        self._mutations = PostgresJobMutationStore(connection_factory)

    def ensure_worker_schema(self) -> None:
        """Create the concurrency-specific lease objects idempotently."""
        self._claims.ensure_schema()

    def create_playlist_job(
        self,
        *,
        user_id: str,
        playlist_id: str,
        playlist_title: str,
        entries: list[PlaylistVideoEntry],
        reflection: ReflectionInput | None,
        force_refresh: bool,
    ) -> BackgroundJob:
        return self._repository.create_playlist_job(
            user_id=user_id,
            playlist_id=playlist_id,
            playlist_title=playlist_title,
            entries=entries,
            reflection=reflection,
            force_refresh=force_refresh,
        )

    def get_job(self, job_id: str, *, user_id: str) -> BackgroundJob:
        return self._repository.get_job(job_id, user_id=user_id)

    def get_job_detail(self, job_id: str, *, user_id: str) -> JobDetailResponse:
        return self._repository.get_job_detail(job_id, user_id=user_id)

    def list_runnable_jobs(self) -> list[str]:
        return self._repository.list_runnable_jobs()

    def claim_next_item(self, *, worker_id: str, user_id: str | None = None) -> tuple[str, str, str] | None:
        claimed = self._claims.claim_next_item(worker_id=worker_id, user_id=user_id)
        if claimed is None:
            return None
        return claimed.job_id, claimed.item_key, claimed.url

    def heartbeat_item(self, *, job_id: str, item_key: str, worker_id: str) -> bool:
        return self._claims.heartbeat_item(job_id=job_id, item_key=item_key, worker_id=worker_id)

    def complete_item(
        self,
        *,
        job_id: str,
        item_key: str,
        status: str,
        error: str | None = None,
        worker_id: str | None = None,
    ) -> bool:
        if worker_id is None or not worker_id.strip():
            raise ValueError("worker_id is required for Postgres job completion")
        return self._claims.complete_item(
            job_id=job_id,
            item_key=item_key,
            status=status,
            error=error,
            worker_id=worker_id,
        )

    def set_paused(self, job_id: str, *, user_id: str, paused: bool) -> BackgroundJob:
        current = self.get_job(job_id, user_id=user_id)
        if current.status in {"completed", "cancelled", "failed"} and not paused:
            raise AppError(f"Cannot resume a {current.status} job.")
        if not self._controls.set_paused(job_id=job_id, user_id=user_id, paused=paused):
            raise KeyError(f"Job not found: {job_id}")
        return self.get_job(job_id, user_id=user_id)

    def cancel_job(self, job_id: str, *, user_id: str) -> BackgroundJob:
        current = self.get_job(job_id, user_id=user_id)
        if current.status in {"completed", "cancelled"}:
            return current
        if not self._controls.cancel_job(job_id=job_id, user_id=user_id):
            raise KeyError(f"Job not found: {job_id}")
        return self.get_job(job_id, user_id=user_id)

    def retry_failed(self, job_id: str, *, user_id: str) -> BackgroundJob:
        current = self.get_job(job_id, user_id=user_id)
        if current.status == "cancelled":
            raise AppError("Cannot retry a cancelled job. Start a new playlist import.")
        if not self._mutations.retry_failed(job_id=job_id, user_id=user_id):
            raise KeyError(f"Job not found: {job_id}")
        return self.get_job(job_id, user_id=user_id)

    def delete_job(self, job_id: str, *, user_id: str) -> None:
        # Establish tenant ownership first so destructive writes fail closed.
        self.get_job(job_id, user_id=user_id)
        if not self._mutations.delete_job(job_id=job_id, user_id=user_id):
            raise KeyError(f"Job not found: {job_id}")
