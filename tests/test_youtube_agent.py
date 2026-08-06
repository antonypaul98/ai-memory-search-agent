"""V1-2 YouTube Memory Agent tests — connector, model, duplicates, pipeline, APIs."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.schema import SCHEMA_VERSION, migrate
from app.db.youtube_memory_store import YouTubeMemoryStore, new_memory_id
from app.models.user import LOCAL_DEFAULT_USER_ID
from app.models.video import SearchFilters, SearchResponse, SearchResultItem, SourceType, VideoMetadata
from app.models.reflection import ReflectionDisplay, UsageStats
from app.models.youtube_memory import YouTubeMemory
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.services.sources.base_source import (
    NormalizedItem,
    ProcessingStatus,
    TranscriptAvailability,
    TranscriptKind,
)
from app.services.sources.youtube_connector import CONNECTOR_ID, YouTubeConnector
from app.services.sources import get_connector_registry, reset_connector_registry_cache
from app.services.youtube_duplicate_service import YouTubeDuplicateDetector
from app.services.metadata_service import MetadataService
from app.services.search_service import SearchService, _passes_filters
from app.services.ingest_service import IngestService


@pytest.fixture(autouse=True)
def _reset_connectors():
    reset_connector_registry_cache()
    yield
    reset_connector_registry_cache()


class TestSchemaV6:
    def test_migrates_to_v6(self, tmp_path) -> None:
        settings = Settings(sqlite_path=str(tmp_path / "v6.db"))
        migrate(settings)
        import sqlite3

        conn = sqlite3.connect(settings.sqlite_path)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert version == SCHEMA_VERSION
        assert SCHEMA_VERSION >= 6
        assert "youtube_memories" in tables
        assert "connector_retry_queue" in tables
        assert "pipeline_runs" in tables
        assert "connector_metrics" in tables


class TestYouTubeMemoryModel:
    def test_validation_rejects_bad_video_id(self) -> None:
        with pytest.raises(Exception):
            YouTubeMemory(
                memory_id="m1",
                user_id="u1",
                video_id="bad id",
                url="https://www.youtube.com/watch?v=abcdefghijk",
                title="T",
                saved_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
            )

    def test_valid_memory(self) -> None:
        mem = YouTubeMemory(
            memory_id=new_memory_id(),
            user_id=LOCAL_DEFAULT_USER_ID,
            video_id="abcdefghijk",
            url="https://www.youtube.com/watch?v=abcdefghijk",
            title="Building Agents",
            channel="Demo",
            channel_id="UC123",
            published_at="2024-01-15",
            duration_sec=600,
            tags=["ai", "agents"],
            saved_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
            processing_status=ProcessingStatus.COMPLETED,
        )
        assert mem.source_type == SourceType.YOUTUBE
        assert mem.connector_id == "youtube.v1"


class TestConnectorRegistry:
    def test_resolves_youtube(self) -> None:
        reg = get_connector_registry()
        assert CONNECTOR_ID in reg.list_connectors()
        conn = reg.resolve_for_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert isinstance(conn, YouTubeConnector)
        ref = conn.parse_ref("https://youtu.be/dQw4w9WgXcQ")
        assert ref.external_id == "dQw4w9WgXcQ"


class TestYouTubeConnectorUnit:
    def test_normalize_upload_date(self) -> None:
        from app.services.sources.youtube_connector import _normalize_upload_date

        assert _normalize_upload_date("20240115") == "2024-01-15"
        assert _normalize_upload_date(None) is None

    def test_fetch_metadata_via_connector(self) -> None:
        connector = YouTubeConnector()
        fake_info = {
            "id": "abcdefghijk",
            "title": "MCP Explained",
            "description": "About MCP",
            "uploader": "Creator",
            "channel_id": "UCabc",
            "thumbnail": "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg",
            "duration": 120,
            "webpage_url": "https://www.youtube.com/watch?v=abcdefghijk",
            "upload_date": "20240301",
            "tags": ["mcp", "ai"],
            "categories": ["Science & Technology"],
            "language": "en",
        }
        with patch("yt_dlp.YoutubeDL") as ydl_cls:
            instance = ydl_cls.return_value.__enter__.return_value
            instance.extract_info.return_value = fake_info
            item = connector.fetch_metadata(connector.parse_ref(fake_info["webpage_url"]))
        assert isinstance(item, NormalizedItem)
        assert item.external_id == "abcdefghijk"
        assert item.author == "Creator"
        assert item.published_at == "2024-03-01"
        assert "mcp" in item.tags
        assert item.raw_metadata["channel_id"] == "UCabc"

    def test_metadata_service_delegates_to_connector(self) -> None:
        service = MetadataService()
        with patch.object(YouTubeConnector, "fetch_metadata") as mock_fetch:
            mock_fetch.return_value = NormalizedItem(
                source_type=SourceType.YOUTUBE,
                connector_id=CONNECTOR_ID,
                external_id="abcdefghijk",
                canonical_url="https://www.youtube.com/watch?v=abcdefghijk",
                title="T",
                author="C",
                raw_metadata={"channel_id": "UC1"},
            )
            meta = service.fetch_metadata("https://www.youtube.com/watch?v=abcdefghijk")
        assert isinstance(meta, VideoMetadata)
        assert meta.channel_id == "UC1"
        assert meta.video_id == "abcdefghijk"


class TestYouTubeMemoryStore:
    def test_upsert_and_metrics(self, test_settings: Settings) -> None:
        store = YouTubeMemoryStore(test_settings)
        now = datetime.now(timezone.utc).isoformat()
        mem = YouTubeMemory(
            memory_id=new_memory_id(),
            user_id=LOCAL_DEFAULT_USER_ID,
            video_id="vid12345678",
            url="https://www.youtube.com/watch?v=vid12345678",
            title="RAG Deep Dive",
            channel="AI Lab",
            saved_at=now,
            updated_at=now,
            content_hash="abc",
            processing_status=ProcessingStatus.COMPLETED,
        )
        store.upsert(mem)
        loaded = store.get("vid12345678", user_id=LOCAL_DEFAULT_USER_ID)
        assert loaded is not None
        assert loaded.title == "RAG Deep Dive"
        store.bump_metric("transcript_success", 1)
        diag = store.diagnostics()
        assert diag.videos_saved >= 1
        assert diag.transcript_success >= 1


class TestDuplicateDetector:
    def test_exact_video_id(self, test_settings: Settings) -> None:
        store = YouTubeMemoryStore(test_settings)
        now = datetime.now(timezone.utc).isoformat()
        store.upsert(
            YouTubeMemory(
                memory_id=new_memory_id(),
                user_id=LOCAL_DEFAULT_USER_ID,
                video_id="dup12345678",
                url="https://www.youtube.com/watch?v=dup12345678",
                title="Original",
                saved_at=now,
                updated_at=now,
                processing_status=ProcessingStatus.COMPLETED,
            )
        )
        detector = YouTubeDuplicateDetector(store)
        report = detector.check_url(
            "https://youtu.be/dup12345678", user_id=LOCAL_DEFAULT_USER_ID
        )
        assert report.is_duplicate
        assert report.match_type == "exact_video_id"

    def test_same_video_different_url(self) -> None:
        assert YouTubeDuplicateDetector.same_video_different_url(
            "https://www.youtube.com/watch?v=abcdefghijk",
            "https://youtu.be/abcdefghijk",
        )


class TestSearchFilters:
    def test_passes_filters(self) -> None:
        item = SearchResultItem(
            video_id="v1",
            title="Kubernetes tutorial",
            channel="DevOps Pro",
            thumbnail="",
            url="https://youtube.com/watch?v=v1",
            original_url="https://youtube.com/watch?v=v1",
            timestamp_url="https://youtube.com/watch?v=v1&t=0",
            matched_text="deploy cluster",
            relevance_score=0.8,
            why_matched="transcript",
            confidence=0.8,
            duration=600,
            language="en",
            transcript_available=True,
            published_at="2024-06-01",
            reflection=ReflectionDisplay(),
            usage=UsageStats(),
        )
        assert _passes_filters(item, SearchFilters(channel="devops"))
        assert not _passes_filters(item, SearchFilters(channel="unrelated"))
        assert _passes_filters(item, SearchFilters(language="en", min_confidence=0.5))
        assert not _passes_filters(item, SearchFilters(duration_max=100))


class TestYouTubeAPI:
    def test_diagnostics_endpoint(self, client: TestClient) -> None:
        resp = client.get("/api/v1/youtube/diagnostics")
        assert resp.status_code == 200
        body = resp.json()
        assert body["connector_id"] == "youtube.v1"
        assert "videos_saved" in body

    def test_memory_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/v1/youtube/memories/missingvideo12")
        assert resp.status_code == 404

    def test_search_accepts_filters(self, client: TestClient) -> None:
        with patch.object(SearchService, "search") as mock_search:
            mock_search.return_value = SearchResponse(
                query="rag", results=[], filters_applied={"channel": "AI"}
            )
            resp = client.get("/api/v1/search", params={"q": "rag", "channel": "AI"})
            assert resp.status_code == 200
            assert mock_search.called


class TestIngestUsesConnector:
    def test_ingest_pipeline_persists_youtube_memory(self, test_settings: Settings) -> None:
        meta = VideoMetadata(
            video_id="ing12345678",
            title="Ingest Test",
            channel="Chan",
            webpage_url="https://www.youtube.com/watch?v=ing12345678",
            channel_id="UC1",
            published_at="2024-01-01",
            tags=["test"],
            content_hash="hash1",
        )
        transcript = TranscriptResult(
            video_id="ing12345678",
            canonical_url=meta.webpage_url,
            segments=[
                TranscriptSegment(
                    text="hello world about RAG systems",
                    start_time_sec=0,
                    duration_sec=2,
                )
            ]
            * 5,
            full_text=("hello world about RAG systems " * 5).strip(),
            language="en",
            is_generated=False,
        )
        service = IngestService(settings=test_settings)
        with (
            patch.object(service._metadata, "fetch_metadata", return_value=meta),
            patch.object(
                service._transcript,
                "detect_availability",
                return_value=TranscriptAvailability.AVAILABLE,
            ),
            patch(
                "app.services.ingest_service._fetch_transcript_cached",
                return_value=transcript,
            ),
            patch("app.services.ingest_service.embed_texts") as emb,
            patch.object(service._repository, "upsert_chunks", return_value=3),
            patch.object(service._hstore, "delete_video"),
            patch.object(service._fts, "delete_video"),
            patch.object(service._fts, "upsert"),
            patch.object(service._hstore, "upsert_capsule"),
            patch.object(service._hstore, "upsert_sections"),
            patch("app.services.ingest_service.store_capsule_json"),
            patch.object(service._registry, "upsert_video"),
            patch.object(service._registry, "is_indexed", return_value=False),
            patch.object(service._repository, "video_exists", return_value=False),
            patch.object(service._memory_os, "finalize_ingest"),
            patch("app.services.ingest_service._transcript_unchanged", return_value=False),
        ):
            emb.side_effect = lambda texts, settings=None: [[0.01] * 16 for _ in texts]
            result = service.ingest_single_url(meta.webpage_url, user_id=LOCAL_DEFAULT_USER_ID)

        assert result.success
        saved = YouTubeMemoryStore(test_settings).get(
            "ing12345678", user_id=LOCAL_DEFAULT_USER_ID
        )
        assert saved is not None
        assert saved.processing_status == ProcessingStatus.COMPLETED
        assert saved.channel_id == "UC1"
        stages = {s.stage for s in result.stages}
        assert "metadata" in stages
        assert "transcript" in stages
        assert "embedding" in stages
        assert "completed" in stages
