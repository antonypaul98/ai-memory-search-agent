"""Tests for ingest service batch behavior."""

from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings
from app.db.chroma_client import reset_chroma_cache
from app.db.video_registry import reset_video_registry_cache
from app.db.repositories.memory_repository import MemoryRepository
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.models.video import VideoMetadata, SourceType
from app.services.ingest_service import IngestService, MAX_BATCH_SIZE, clear_transcript_cache
from app.services.sources.base_source import TranscriptAvailability


@pytest.fixture
def ingest_settings(tmp_path) -> Settings:
    reset_video_registry_cache()
    return Settings(
        chroma_persist_dir=str(tmp_path / "chroma"),
        chroma_collection_name="ingest_test",
        sqlite_path=str(tmp_path / "videos.db"),
        chunk_size=200,
        chunk_overlap=20,
        embedding_model="test-model",
        ingest_concurrency=1,
        hierarchical_retrieval_enabled=False,
        semantic_cache_enabled=False,
        jobs_enabled=False,
    )


def _metadata() -> VideoMetadata:
    return VideoMetadata(
        video_id="abc12345678",
        title="Demo Video",
        description="desc",
        channel="Demo Channel",
        thumbnail="https://img.example/thumb.jpg",
        duration=120.0,
        webpage_url="https://www.youtube.com/watch?v=abc12345678",
        source_type=SourceType.YOUTUBE,
    )


def _transcript(*, generated: bool = False) -> TranscriptResult:
    return TranscriptResult(
        video_id="abc12345678",
        canonical_url="https://www.youtube.com/watch?v=abc12345678",
        segments=[
            TranscriptSegment(text="healthy meal prep", start_time_sec=0.0, duration_sec=2.0),
            TranscriptSegment(text="high protein breakfast", start_time_sec=2.0, duration_sec=2.0),
        ],
        full_text="healthy meal prep high protein breakfast",
        language="en",
        is_generated=generated,
    )


class TestIngestService:
    def test_batch_continues_after_failure(self, ingest_settings: Settings) -> None:
        reset_chroma_cache()
        reset_video_registry_cache()
        clear_transcript_cache()
        metadata_service = MagicMock()
        metadata_service.fetch_metadata.side_effect = [
            _metadata(),
            Exception("metadata failed"),
        ]

        transcript_service = MagicMock()
        transcript_service.detect_availability.return_value = TranscriptAvailability.AVAILABLE
        transcript_service.fetch_transcript.return_value = _transcript()

        repository = MemoryRepository(ingest_settings)
        service = IngestService(
            settings=ingest_settings,
            metadata_service=metadata_service,
            transcript_service=transcript_service,
            repository=repository,
        )

        def fake_embed(texts, settings=None):
            return [[0.1, 0.2] for _ in texts]

        with patch("app.services.ingest_service.embed_texts", side_effect=fake_embed):
            response = service.ingest_batch(
                [
                    "https://www.youtube.com/watch?v=abc12345678",
                    "https://www.youtube.com/watch?v=bad00000000",
                ]
            )

        assert response.total == 2
        assert response.succeeded == 1
        assert response.failed == 1
        assert response.results[0].success is True
        assert (response.results[0].chunk_count or 0) >= 1
        assert response.results[1].success is False
        assert "metadata failed" in (response.results[1].error or "")

    def test_replaces_existing_video_chunks(self, ingest_settings: Settings) -> None:
        reset_chroma_cache()
        reset_video_registry_cache()
        clear_transcript_cache()
        metadata_service = MagicMock()
        metadata_service.fetch_metadata.return_value = _metadata()

        transcript_service = MagicMock()
        transcript_service.detect_availability.return_value = TranscriptAvailability.AVAILABLE
        transcript_service.fetch_transcript.return_value = _transcript()

        repository = MemoryRepository(ingest_settings)
        service = IngestService(
            settings=ingest_settings,
            metadata_service=metadata_service,
            transcript_service=transcript_service,
            repository=repository,
        )

        url = "https://www.youtube.com/watch?v=abc12345678"

        def fake_embed(texts, settings=None):
            return [[0.1, 0.2] for _ in texts]

        with patch("app.services.ingest_service.embed_texts", side_effect=fake_embed):
            first = service.ingest_batch([url])
            second = service.ingest_batch([url], force_refresh=True)

        assert first.succeeded == 1
        assert second.succeeded == 1
        chunk_count = first.results[0].chunk_count or 0
        assert repository.check_connection()["document_count"] == chunk_count

    def test_invalid_url_is_reported(self, ingest_settings: Settings) -> None:
        reset_chroma_cache()
        service = IngestService(settings=ingest_settings)
        response = service.ingest_batch(["https://example.com/not-youtube"])
        assert response.failed == 1
        assert response.results[0].success is False

    def test_empty_transcript_fails_gracefully(self, ingest_settings: Settings) -> None:
        reset_chroma_cache()
        reset_video_registry_cache()
        clear_transcript_cache()
        metadata_service = MagicMock()
        metadata_service.fetch_metadata.return_value = _metadata()
        transcript_service = MagicMock()
        transcript_service.detect_availability.return_value = TranscriptAvailability.AVAILABLE
        transcript_service.fetch_transcript.return_value = TranscriptResult(
            video_id="abc12345678",
            canonical_url="https://www.youtube.com/watch?v=abc12345678",
            segments=[],
            full_text="",
            language="en",
            is_generated=False,
        )

        service = IngestService(
            settings=ingest_settings,
            metadata_service=metadata_service,
            transcript_service=transcript_service,
            repository=MemoryRepository(ingest_settings),
        )
        response = service.ingest_batch(
            ["https://www.youtube.com/watch?v=abc12345678"],
            force_refresh=True,
        )
        assert response.failed == 1
        assert "empty" in (response.results[0].error or "").lower()

    def test_batch_limit_raises(self, ingest_settings: Settings) -> None:
        service = IngestService(settings=ingest_settings)
        urls = ["https://youtu.be/dQw4w9WgXcQ"] * (MAX_BATCH_SIZE + 1)
        with pytest.raises(ValueError, match="Batch limit"):
            service.ingest_batch(urls)
