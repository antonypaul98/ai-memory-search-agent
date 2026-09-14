"""Real-Postgres multi-worker claim acceptance with relational SQLite rejected."""
from __future__ import annotations

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.postgres_job_store import PostgresJobStore
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.services import job_worker as worker_module
from app.services.playlist_service import PlaylistVideoEntry


pytestmark = pytest.mark.skipif(
    not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"),
    reason="real Postgres DSN required",
)


def test_postgres_workers_cannot_double_claim_same_item_without_sqlite(monkeypatch, tmp_path):
    settings = Settings(
        _env_file=None,
        **{field: "postgres" for field in RELATIONAL_STORE_BACKEND_FIELDS},
        postgres_dsn_env="MEMORY_AGENT_TEST_POSTGRES_DSN",
        sqlite_path=str(tmp_path / "must-not-exist.db"),
        jobs_enabled=True,
        worker_mode="worker",
        semantic_cache_enabled=False,
    )

    def reject_sqlite(*args, **kwargs):
        raise AssertionError("production Postgres workers opened relational SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject_sqlite)
    monkeypatch.setattr(worker_module, "IngestService", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(worker_module, "get_job_queue_transport", MagicMock(return_value=MagicMock()))

    worker_a = worker_module.JobWorker(settings)
    worker_b = worker_module.JobWorker(settings)
    assert isinstance(worker_a._store, PostgresJobStore)
    assert isinstance(worker_b._store, PostgresJobStore)

    nonce = uuid4().hex
    owner = f"multiworker-owner-{nonce}"
    url = f"https://youtu.be/{nonce[:11]}"
    job = worker_a._store.create_playlist_job(
        user_id=owner,
        playlist_id=f"playlist-{nonce}",
        playlist_title="P03 multi-worker acceptance",
        entries=[PlaylistVideoEntry(video_id=f"video-{nonce}", url=url, title="fixture")],
        reflection=None,
        force_refresh=False,
    )

    barrier = Barrier(2)

    def claim(worker, worker_id):
        barrier.wait(timeout=5)
        return worker._store.claim_next_item(worker_id=worker_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(claim, worker_a, "worker-a")
        future_b = pool.submit(claim, worker_b, "worker-b")
        results = [future_a.result(timeout=10), future_b.result(timeout=10)]

    claimed = [result for result in results if result is not None]
    empty = [result for result in results if result is None]
    assert len(claimed) == 1
    assert len(empty) == 1
    assert claimed[0][0] == job.job_id
    assert claimed[0][2] == url

    detail = worker_a._store.get_job_detail(job.job_id, user_id=owner)
    assert detail.processing == 1
    assert detail.completed == 0
    assert detail.failed == 0
    assert not (tmp_path / "must-not-exist.db").exists()

    worker_a._store.delete_job(job.job_id, user_id=owner)
