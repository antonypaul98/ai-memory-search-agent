"""Regression coverage for tenant-aware lexical mutations during ingestion."""

from unittest.mock import MagicMock, patch

from app.config import Settings
from app.db.chroma_client import reset_chroma_cache
from app.db.repositories.memory_repository import MemoryRepository
from app.db.video_registry import reset_video_registry_cache
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.models.video import SourceType, VideoMetadata
from app.services.ingest_service import IngestService, clear_transcript_cache
from app.services.sources.base_source import TranscriptAvailability


def _settings(tmp_path) -> Settings:
    reset_chroma_cache()
    reset_video_registry_cache()
    clear_transcript_cache()
    return Settings(
        chroma_persist_dir=str(tmp_path / "chroma"),
        chroma_collection_name="fts_ingest_tenant_test",
        sqlite_path=str(tmp_path / "videos.db"),
        chunk_size=200,
        chunk_overlap=20,
        embedding_model="test-model",
        ingest_concurrency=1,
        hierarchical_retrieval_enabled=True,
        semantic_cache_enabled=False,
        jobs_enabled=False,
    )


def _metadata() -> VideoMetadata:
    return VideoMetadata(
        video_id="abc12345678",
        title="Tenant Demo",
        description="tenant-aware lexical indexing",
        channel="Demo Channel",
        thumbnail="https://img.example/thumb.jpg",
        duration=120.0,
        webpage_url="https://www.youtube.com/watch?v=abc12345678",
        source_type=SourceType.YOUTUBE,
    )


def _transcript() -> TranscriptResult:
    return TranscriptResult(
        video_id="abc12345678",
        canonical_url="https://www.youtube.com/watch?v=abc12345678",
        segments=[
            TranscriptSegment(
                text="tenant scoped lexical evidence",
                start_time_sec=0.0,
                duration_sec=2.0,
            )
        ],
        full_text="tenant scoped lexical evidence",
        language="en",
        is_generated=False,
    )


def test_ingest_routes_all_fts_mutations_with_resolved_tenant(tmp_path) -> None:
    settings = _settings(tmp_path)
    metadata_service = MagicMock()
    metadata_service.fetch_metadata.return_value = _metadata()
    transcript_service = MagicMock()
    transcript_service.detect_availability.return_value = TranscriptAvailability.AVAILABLE
    transcript_service.fetch_transcript.return_value = _transcript()
    fts = MagicMock()

    with patch("app.services.ingest_service.get_fts_index", return_value=fts):
        service = IngestService(
            settings=settings,
            metadata_service=metadata_service,
            transcript_service=transcript_service,
            repository=MemoryRepository(settings),
        )

    # Keep this regression focused on lexical routing rather than hierarchical
    # persistence, ingest-artifact persistence, or canonical-memory side effects.
    service._hstore = MagicMock()
    service._memory_os = MagicMock()

    def fake_embed(texts, settings=None):
        return [[0.1, 0.2] for _ in texts]

    with (
        patch("app.services.ingest_service.embed_texts", side_effect=fake_embed),
        patch.object(service._artifact_store, "store_capsule_json"),
        patch.object(service._artifact_store, "store_transcript_hash"),
    ):
        response = service.ingest_batch(
            ["https://www.youtube.com/watch?v=abc12345678"],
            force_refresh=True,
            user_id="tenant-a",
        )

    assert response.succeeded == 1
    fts.delete_video.assert_called_once_with("abc12345678", user_id="tenant-a")
    assert fts.upsert.call_count >= 2
    for call in fts.upsert.call_args_list:
        assert call.kwargs["user_id"] == "tenant-a"


def test_ingest_constructs_fts_through_configured_factory(tmp_path) -> None:
    settings = _settings(tmp_path)
    fts = MagicMock()

    with patch("app.services.ingest_service.get_fts_index", return_value=fts) as factory:
        service = IngestService(settings=settings)

    factory.assert_called_once_with(settings)
    assert service._fts is fts
