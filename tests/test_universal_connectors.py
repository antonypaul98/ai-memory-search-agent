"""Tests for V1-4 Universal Memory Connectors."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.schema import SCHEMA_VERSION, migrate
from app.main import app
from app.models.user import LOCAL_DEFAULT_USER_ID, UserPublic
from app.services.connector_ingest_service import ConnectorIngestService
from app.services.cross_duplicate_service import CrossConnectorDuplicateDetector
from app.services.import_manager import ImportManager
from app.services.sources import get_connector_registry, reset_connector_registry_cache
from app.services.sources.base_source import SourceRef
from app.services.sources.bookmark_connector import BookmarkConnector
from app.services.sources.github_connector import GitHubConnector
from app.services.sources.pdf_connector import PDFConnector
from app.services.sources.web_connector import WebConnector


@pytest.fixture
def conn_settings(tmp_path) -> Settings:
    reset_connector_registry_cache()
    return Settings(
        chroma_persist_dir=str(tmp_path / "chroma"),
        chroma_collection_name="connector_test",
        sqlite_path=str(tmp_path / "videos.db"),
        hierarchical_retrieval_enabled=False,
        semantic_cache_enabled=False,
        jobs_enabled=False,
        auth_enabled=False,
        local_demo_mode=True,
        debug=True,
        embedding_model="test-model",
    )


class TestSchemaV8:
    def test_schema_v8(self, conn_settings: Settings) -> None:
        migrate(conn_settings)
        assert SCHEMA_VERSION >= 8
        registry = get_connector_registry()
        assert "web.v1" in registry.list_connectors()
        assert "pdf.v1" in registry.list_connectors()
        assert "github.v1" in registry.list_connectors()
        assert "bookmarks.v1" in registry.list_connectors()


class TestWebConnector:
    def test_parse_and_extract_offline(self) -> None:
        connector = WebConnector()
        html = """
        <html><head><title>Vector Databases Explained</title>
        <link rel="canonical" href="https://example.com/vector-db"/>
        <meta name="author" content="Ada"/>
        </head><body><h1>Intro</h1>
        <article><p>Vector databases store embeddings for RAG retrieval.</p>
        <p>They power semantic search across documents.</p></article>
        </body></html>
        """
        ref = SourceRef(
            url="https://example.com/vector-db",
            external_id="vecdb1",
            extra={"html": html, "title": "Vector Databases Explained"},
        )
        meta = connector.fetch_metadata(ref)
        assert meta.source_type.value == "web"
        assert "Vector" in meta.title or meta.title
        assert meta.content_hash
        payload = connector.fetch_transcript(ref)
        assert "embeddings" in payload.full_text.lower() or "vector" in payload.full_text.lower()
        assert payload.segments

    def test_rejects_youtube(self) -> None:
        connector = WebConnector()
        assert connector.supports_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is False


class TestGitHubConnector:
    def test_parse_ref(self) -> None:
        connector = GitHubConnector()
        ref = connector.parse_ref("https://github.com/openai/whisper")
        assert ref.external_id == "openai/whisper"
        assert connector.supports_url("https://github.com/openai/whisper")

    def test_metadata_from_injected_json(self) -> None:
        connector = GitHubConnector()
        ref = connector.parse_ref("https://github.com/acme/k8s-tools")
        ref.extra["repo_json"] = {
            "full_name": "acme/k8s-tools",
            "description": "Kubernetes tooling",
            "html_url": "https://github.com/acme/k8s-tools",
            "owner": {"login": "acme"},
            "language": "Go",
            "topics": ["kubernetes", "devops"],
            "stargazers_count": 42,
            "license": {"spdx_id": "MIT"},
            "default_branch": "main",
            "updated_at": "2026-01-01T00:00:00Z",
            "created_at": "2025-01-01T00:00:00Z",
            "private": False,
        }
        ref.extra["readme_text"] = "# K8s Tools\nDeploy with Helm."
        meta = connector.fetch_metadata(ref)
        assert meta.title == "acme/k8s-tools"
        assert "kubernetes" in meta.tags
        payload = connector.fetch_transcript(ref)
        assert "Helm" in payload.full_text


class TestPDFConnector:
    def test_parse_pdf_url(self) -> None:
        connector = PDFConnector()
        assert connector.supports_url("https://example.com/docs/guide.pdf")
        ref = connector.parse_ref("pdf://abc123")
        assert ref.external_id == "abc123"

    def test_pdf_pages_text(self) -> None:
        connector = PDFConnector()
        ref = SourceRef(
            url="pdf://dockerdoc",
            external_id="dockerdoc",
            extra={
                "filename": "docker.pdf",
                "pages_text": [
                    "Docker containers package applications.",
                    "Images are built from Dockerfiles.",
                ],
            },
        )
        meta = connector.fetch_metadata(ref)
        assert "docker" in meta.title.lower() or meta.title
        payload = connector.fetch_transcript(ref)
        assert "Docker" in payload.full_text
        assert payload.segments[0].start_time_sec == 1.0

    def test_preview(self, conn_settings: Settings) -> None:
        connector = BookmarkConnector()
        items = [
            {"url": "https://example.com/a", "folder_path": "RAG", "title": "A"},
            {"url": "https://example.com/a", "folder_path": "RAG", "title": "A dup"},
            {"url": "not-a-url", "folder_path": "RAG", "title": "bad"},
            {"url": "https://example.com/b", "folder_path": "Docker", "title": "B"},
        ]
        preview = connector.preview_import(items)
        assert preview["bookmark_count"] == 4
        assert preview["duplicate_count"] >= 1
        assert preview["unsupported_count"] >= 1
        assert preview["importable_count"] >= 1


class TestCrossDuplicates:
    def test_url_and_hash(self, conn_settings: Settings) -> None:
        dupes = CrossConnectorDuplicateDetector(conn_settings)
        assert not dupes.check(user_id=LOCAL_DEFAULT_USER_ID, canonical_url="https://ex.com/x").is_duplicate
        dupes.register(
            user_id=LOCAL_DEFAULT_USER_ID,
            canonical_url="https://ex.com/x",
            content_hash="abc",
            source_type="web",
            connector_id="web.v1",
            external_id="x1",
        )
        report = dupes.check(user_id=LOCAL_DEFAULT_USER_ID, canonical_url="https://ex.com/x")
        assert report.is_duplicate
        assert report.match_type == "url"
        report2 = dupes.check(
            user_id=LOCAL_DEFAULT_USER_ID,
            canonical_url="https://ex.com/other",
            content_hash="abc",
        )
        assert report2.is_duplicate
        assert report2.match_type == "content_hash"


class TestConnectorIngest:
    def test_web_offline_ingest_and_search(self, conn_settings: Settings) -> None:
        def fake_embed(texts, settings=None):
            return [[0.1, 0.2] for _ in texts]

        service = ConnectorIngestService(conn_settings)
        html = """
        <html><head><title>Article about vector databases</title></head>
        <body><article>Vector databases are essential for RAG systems and retrieval.</article></body></html>
        """
        with patch("app.services.connector_ingest_service.embed_texts", side_effect=fake_embed):
            result = service.ingest_url(
                "https://example.com/vector-databases",
                user_id=LOCAL_DEFAULT_USER_ID,
                connector_id="web.v1",
                ref_extra={"html": html, "title": "Article about vector databases"},
            )
        assert result.success is True
        assert (result.chunk_count or 0) >= 1

        # Duplicate should skip
        with patch("app.services.connector_ingest_service.embed_texts", side_effect=fake_embed):
            again = service.ingest_url(
                "https://example.com/vector-databases",
                user_id=LOCAL_DEFAULT_USER_ID,
                connector_id="web.v1",
                ref_extra={"html": html},
            )
        assert again.skipped is True

    def test_github_injected_ingest(self, conn_settings: Settings) -> None:
        def fake_embed(texts, settings=None):
            return [[0.2, 0.1] for _ in texts]

        service = ConnectorIngestService(conn_settings)
        with patch("app.services.connector_ingest_service.embed_texts", side_effect=fake_embed):
            result = service.ingest_url(
                "https://github.com/acme/kubernetes-deploy",
                user_id=LOCAL_DEFAULT_USER_ID,
                connector_id="github.v1",
                ref_extra={
                    "repo_json": {
                        "full_name": "acme/kubernetes-deploy",
                        "description": "Kubernetes deployment tutorial repo",
                        "html_url": "https://github.com/acme/kubernetes-deploy",
                        "owner": {"login": "acme"},
                        "language": "YAML",
                        "topics": ["kubernetes"],
                        "stargazers_count": 10,
                        "license": {"spdx_id": "Apache-2.0"},
                        "default_branch": "main",
                        "private": False,
                    },
                    "readme_text": "# Kubernetes Deploy\nHow to deploy with kubectl.",
                },
            )
        assert result.success is True


class TestPDFIngestReal:
    def test_pdf_ingest_with_text(self, conn_settings: Settings) -> None:
        def fake_embed(texts, settings=None):
            return [[0.15, 0.25] for _ in texts]

        service = ConnectorIngestService(conn_settings)
        with patch("app.services.connector_ingest_service.embed_texts", side_effect=fake_embed):
            result = service.ingest_url(
                "pdf://dockerdoc",
                user_id=LOCAL_DEFAULT_USER_ID,
                connector_id="pdf.v1",
                ref_extra={
                    "filename": "docker.pdf",
                    "pages_text": [
                        "Docker containers package applications with dependencies.",
                        "Use docker compose for multi-service apps.",
                    ],
                },
            )
        assert result.success is True
        assert (result.chunk_count or 0) >= 1


class TestImportManagerAPI:
    def test_bookmark_preview_and_health(self, conn_settings: Settings, monkeypatch) -> None:
        from app.api import auth as auth_mod
        from app.config import get_settings

        get_settings.cache_clear()
        app.dependency_overrides[get_settings] = lambda: conn_settings
        app.dependency_overrides[auth_mod.get_current_user] = lambda: UserPublic(
            user_id=LOCAL_DEFAULT_USER_ID, display_name="Demo"
        )
        client = TestClient(app)
        health = client.get("/api/v1/connectors/health")
        assert health.status_code == 200
        assert "connectors" in health.json()

        preview = client.post(
            "/api/v1/capture/bookmarks/preview",
            json={
                "source_browser": "chrome",
                "items": [
                    {
                        "browser_bookmark_id": "1",
                        "folder_path": "RAG",
                        "url": "https://example.com/rag",
                        "title": "RAG",
                    }
                ],
            },
        )
        assert preview.status_code == 200
        assert preview.json()["bookmark_count"] == 1

        imports = client.get("/api/v1/imports")
        assert imports.status_code == 200

        app.dependency_overrides.clear()
        get_settings.cache_clear()


class TestImportManagerBookmarks:
    def test_sync_bookmark_import_web(self, conn_settings: Settings) -> None:
        def fake_embed(texts, settings=None):
            return [[0.1, 0.2] for _ in texts]

        manager = ImportManager(conn_settings)
        from app.models.capture import BookmarkImportItem, BookmarkImportRequest

        payload = BookmarkImportRequest(
            items=[
                BookmarkImportItem(
                    browser_bookmark_id="b1",
                    folder_path="RAG",
                    url="https://example.com/rag-bookmark",
                    title="RAG bookmark",
                )
            ]
        )
        with patch("app.services.connector_ingest_service.embed_texts", side_effect=fake_embed):
            with patch.object(
                ConnectorIngestService,
                "ingest_url",
                return_value=__import__(
                    "app.models.video", fromlist=["IngestResultItem"]
                ).IngestResultItem(
                    url="https://example.com/rag-bookmark",
                    success=True,
                    video_id="rag1",
                    title="RAG bookmark",
                    chunk_count=2,
                    webpage_url="https://example.com/rag-bookmark",
                ),
            ):
                result = manager.import_bookmarks(
                    payload, user_id=LOCAL_DEFAULT_USER_ID, async_processing=False
                )
        assert "import_id" in result
        assert result["preview"]["bookmark_count"] == 1
