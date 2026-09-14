"""Real-Postgres worker success acceptance with relational SQLite rejected."""
from __future__ import annotations

import os
import sqlite3
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.postgres_job_store import PostgresJobStore
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.models.video import IngestResultItem
from app.services import job_worker as worker_module
from app.services.playlist_service import PlaylistVideoEntry


pytestmark = pytest.mark.skipif(
    not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"),
    reason="real Postgres DSN required",
)


def test_postgres_worker_success_finalizes_without_relational_sqlite(monkeypatch, tmp_path):
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
        raise AssertionError("production Postgres worker opened relational SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject_sqlite)
    ingest = MagicMock()
    ingest.ingest_single_url.return_value = IngestResultItem(
        url="https://youtu.be/fixture00001",
        success=True,
        skipped=False,
        video_id="fixture00001",
        title="fixture",
    )
    monkeypatch.setattr(worker_module, "IngestService", MagicMock(return_value=ingest))
    monkeypatch.setattr(worker_module, "get_job_queue_transport", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(worker_module, "EventBus", MagicMock(return_value=MagicMock()))

    worker = worker_module.JobWorker(settings)
    assert isinstance(worker._store, PostgresJobStore)

    nonce = uuid4().hex
    owner = f"worker-owner-{nonce}"
    other = f"worker-other-{nonce}"
    url = f"https://youtu.be/{nonce[:11]}"
    job = worker._store.create_playlist_job(
        user_id=owner,
        playlist_id=f"playlist-{nonce}",
        playlist_title="P03 worker success acceptance",
        entries=[PlaylistVideoEntry(video_id=f"video-{nonce}", url=url, title="fixture")],
        reflection=None,
        force_refresh=False,
    )

    claim = worker._store.claim_next_item(worker_id="worker-a")
    assert claim is not None
    job_id, item_key, claimed_url = claim
    assert job_id == job.job_id
    assert claimed_url == url

    worker._process_item(job_id, item_key, claimed_url, worker_id="worker-a")

    ingest.ingest_single_url.assert_called_once_with(
        url,
        user_id=owner,
        reflection=None,
        force_refresh=False,
    )
    detail = worker._store.get_job_detail(job_id, user_id=owner)
    assert detail.completed == 1
    assert detail.failed == 0
    assert detail.processing == 0
    assert detail.items[0].status == "completed"
    assert detail.items[0].error is None
    with pytest.raises(KeyError):
        worker._store.get_job(job_id, user_id=other)
    assert worker._store.claim_next_item(worker_id="worker-b") is None
    assert not (tmp_path / "must-not-exist.db").exists()

    worker._store.delete_job(job_id, user_id=owner)
