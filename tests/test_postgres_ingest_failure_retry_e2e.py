"""Real-Postgres IngestService failure/retry acceptance with relational SQLite rejected."""
from __future__ import annotations

import os
import sqlite3
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.config import Settings
from app.core.exceptions import TranscriptFetchError
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.models.video import VideoMetadata
from app.services.sources.base_source import ProcessingStatus, TranscriptAvailability
import app.services.ingest_service as ingest_module


pytestmark = pytest.mark.skipif(
    not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"),
    reason="real Postgres DSN required",
)


def test_ingest_failure_retry_is_postgres_tenant_scoped_and_sqlite_free(monkeypatch, tmp_path):
    settings = Settings(
        _env_file=None,
        **{field: "postgres" for field in RELATIONAL_STORE_BACKEND_FIELDS},
        postgres_dsn_env="MEMORY_AGENT_TEST_POSTGRES_DSN",
        sqlite_path=str(tmp_path / "must-not-exist.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        hierarchical_retrieval_enabled=False,
        semantic_cache_enabled=False,
        jobs_enabled=False,
    )

    sqlite_attempts: list[tuple[tuple, dict]] = []

    def reject_sqlite(*args, **kwargs):
        sqlite_attempts.append((args, kwargs))
        raise AssertionError("production Postgres ingest failure path opened relational SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject_sqlite)
    monkeypatch.setattr(ingest_module, "HierarchicalStore", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(ingest_module, "UniversalMemoryService", MagicMock(return_value=MagicMock()))

    nonce = uuid4().hex
    video_id = nonce[:11]
    owner = f"ingest-failure-owner-{nonce}"
    other_tenant = f"ingest-failure-other-{nonce}"
    url = f"https://www.youtube.com/watch?v={video_id}"

    metadata = VideoMetadata(
        video_id=video_id,
        title="P03 ingest failure acceptance",
        description="deterministic fixture",
        channel="memory-agent-ci",
        webpage_url=url,
        content_hash=f"hash-{nonce}",
    )
    metadata_service = MagicMock()
    metadata_service.fetch_metadata.return_value = metadata

    transcript_service = MagicMock()
    transcript_service.detect_availability.return_value = TranscriptAvailability.AVAILABLE
    transcript_service.fetch_transcript.side_effect = TranscriptFetchError(
        "Failed to fetch transcript: deterministic acceptance failure"
    )

    repository = MagicMock()
    repository.video_exists.return_value = False

    ingest_module.clear_transcript_cache()
    service = ingest_module.IngestService(
        settings=settings,
        metadata_service=metadata_service,
        transcript_service=transcript_service,
        repository=repository,
    )

    first = service.ingest_single_url(url, user_id=owner, force_refresh=True)
    second = service.ingest_single_url(url, user_id=owner, force_refresh=True)

    assert first.success is False
    assert second.success is False
    assert first.video_id == video_id
    assert second.video_id == video_id
    assert first.error and "deterministic acceptance failure" in first.error
    assert second.error and "deterministic acceptance failure" in second.error
    assert first.stages[-1].stage == "retry"
    assert second.stages[-1].stage == "retry"

    failed_memory = service._yt_store.get(video_id, user_id=owner)
    assert failed_memory is not None
    assert failed_memory.processing_status is ProcessingStatus.FAILED
    assert failed_memory.transcript_status == "failed"
    assert service._yt_store.get(video_id, user_id=other_tenant) is None

    owner_diagnostics = service._yt_store.diagnostics(user_id=owner)
    other_diagnostics = service._yt_store.diagnostics(user_id=other_tenant)
    assert owner_diagnostics.pending_retries == 1
    assert owner_diagnostics.transcript_failure >= 2
    assert owner_diagnostics.retry_count >= 2
    assert other_diagnostics.pending_retries == 0
    assert other_diagnostics.transcript_failure == 0
    assert other_diagnostics.retry_count == 0

    assert sqlite_attempts == []
    assert not (tmp_path / "must-not-exist.db").exists()
