"""Real-Postgres IngestService success acceptance with relational SQLite rejected."""
from __future__ import annotations

import os
import sqlite3
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.models.video import VideoMetadata
from app.services.sources.base_source import TranscriptAvailability
import app.services.ingest_service as ingest_module


pytestmark = pytest.mark.skipif(
    not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"),
    reason="real Postgres DSN required",
)


def test_ingest_success_uses_postgres_relational_stores_without_sqlite(monkeypatch, tmp_path):
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
        raise AssertionError("production Postgres ingest opened relational SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject_sqlite)

    # Vector/hierarchical persistence is intentionally isolated here. This test is
    # the relational Postgres boundary around the real IngestService orchestration.
    monkeypatch.setattr(ingest_module, "HierarchicalStore", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(ingest_module, "UniversalMemoryService", MagicMock(return_value=MagicMock()))

    nonce = uuid4().hex
    video_id = nonce[:11]
    owner = f"ingest-owner-{nonce}"
    url = f"https://www.youtube.com/watch?v={video_id}"

    metadata = VideoMetadata(
        video_id=video_id,
        title="P03 ingest acceptance",
        description="deterministic fixture",
        channel="memory-agent-ci",
        webpage_url=url,
        content_hash=f"hash-{nonce}",
    )
    metadata_service = MagicMock()
    metadata_service.fetch_metadata.return_value = metadata

    transcript = TranscriptResult(
        video_id=video_id,
        canonical_url=url,
        segments=[
            TranscriptSegment(
                text="Postgres is the authoritative relational ingest store.",
                start_time_sec=0.0,
                duration_sec=4.0,
            )
        ],
        full_text="Postgres is the authoritative relational ingest store.",
        language="en",
        is_generated=False,
    )
    transcript_service = MagicMock()
    transcript_service.detect_availability.return_value = TranscriptAvailability.AVAILABLE
    transcript_service.fetch_transcript.return_value = transcript

    repository = MagicMock()
    repository.video_exists.return_value = False
    repository.upsert_chunks.return_value = 1

    capsule = MagicMock()
    capsule.short_summary = "Postgres ingest acceptance"
    capsule.one_line_memory = "Postgres ingest acceptance"
    capsule.sections = []
    capsule.topics = []
    capsule.title = metadata.title
    monkeypatch.setattr(ingest_module, "build_capsule_with_optional_llm", MagicMock(return_value=capsule))
    monkeypatch.setattr(
        ingest_module,
        "embed_texts",
        lambda texts, settings=None: [[0.1, 0.2, 0.3] for _ in texts],
    )
    enrichment = MagicMock()
    enrichment.one_line_memory = "Postgres is authoritative"
    enrichment.why_saved = []
    enrichment.action_items = []
    monkeypatch.setattr(ingest_module, "enrich_video", MagicMock(return_value=enrichment))

    ingest_module.clear_transcript_cache()
    service = ingest_module.IngestService(
        settings=settings,
        metadata_service=metadata_service,
        transcript_service=transcript_service,
        repository=repository,
    )

    result = service.ingest_single_url(url, user_id=owner, force_refresh=True)

    assert result.success is True
    assert result.skipped is False
    assert result.video_id == video_id
    assert result.chunk_count == 1
    assert result.error is None
    assert [stage.stage for stage in result.stages][-2:] == ["indexed", "completed"]
    repository.upsert_chunks.assert_called_once()
    assert sqlite_attempts == []
    assert not (tmp_path / "must-not-exist.db").exists()
