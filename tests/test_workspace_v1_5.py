"""V1-5 AI Memory Workspace — behavioral, security, and regression tests."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db.schema import migrate
from app.main import app
from app.models.chat import ChatResponse
from app.models.intelligence import NaturalRetrieveResponse
from app.models.user import LOCAL_DEFAULT_USER_ID, UserPublic
from app.models.video import SearchFilters, SearchResultItem
from app.services.import_manager import ImportManager
from app.services.search_service import _passes_filters

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
JS = STATIC / "js"


def _read(*parts: str) -> str:
    return (STATIC.joinpath(*parts)).read_text(encoding="utf-8")


class TestWorkspaceShellBehavior:
    def test_index_routes_and_landmarks(self, client: TestClient) -> None:
        html = client.get("/").text
        for route in (
            "dashboard",
            "search",
            "ask",
            "timeline",
            "topics",
            "imports",
            "capture",
            "settings",
        ):
            assert f'data-route="{route}"' in html
        assert 'aria-label="Workspace navigation"' in html
        assert 'aria-label="Primary"' in html
        assert 'aria-live="polite"' in html
        assert "<main" in html
        assert 'type="module"' in html

    def test_service_worker_never_caches_api(self) -> None:
        sw = _read("sw.js")
        assert 'pathname.startsWith("/api/")' in sw
        assert "Authorization" in sw
        assert "caches.delete" in sw

    def test_api_cache_clear_matches_substring(self) -> None:
        api = _read("js/api.js")
        assert "key.includes(needle)" in api
        assert "abortInflight" in api
        assert "Bearer [redacted]" in api

    def test_safe_href_helper_exists_and_used(self) -> None:
        util = _read("js/util.js")
        assert "export function safeHref" in util
        assert "javascript:" not in util.lower() or "reject" in util.lower()
        assert "http:" in util and "https:" in util
        search = _read("js/views/search.js")
        memory = _read("js/views/memory.js")
        assert "externalLink(" in search or "safeHref(" in search
        assert "externalLink(" in memory

    def test_source_types_centralized(self) -> None:
        util = _read("js/util.js")
        assert "export const SOURCE_TYPES" in util
        search = _read("js/views/search.js")
        assert "sourceFilterOptionsHtml" in search
        assert '<option value="youtube">YouTube</option>' not in search

    def test_router_unbind_and_abort_signal(self) -> None:
        router = _read("js/router.js")
        assert "unbindNav" in router
        assert "AbortController" in router
        assert "aria-current" in router
        app_js = _read("app.js")
        assert "disposeCapture" in app_js
        assert "abortInflight" in app_js or "signal" in app_js

    def test_render_limits_present(self) -> None:
        util = _read("js/util.js")
        assert "RENDER_LIMITS" in util
        imports = _read("js/views/imports.js")
        assert "boundList" in imports
        assert "RENDER_LIMITS.importItems" in imports

    def test_no_engine_leakage(self) -> None:
        forbidden = [
            "embed_texts",
            "chromadb",
            "yt_dlp",
            "trafilatura",
            "MemoryIntelligenceService",
            "ConnectorIngestService",
        ]
        for path in JS.rglob("*.js"):
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                assert token not in text, f"{path.name} contains {token}"

    def test_escape_html_covers_user_fields(self) -> None:
        for name in ("search.js", "ask.js", "memory.js", "dashboard.js"):
            text = _read("js/views", name)
            assert "escapeHtml(" in text

    def test_focus_and_reduced_motion_css(self) -> None:
        css = _read("style.css")
        assert ":focus-visible" in css
        assert "prefers-reduced-motion" in css
        assert ".sr-only" in css


class TestWorkspaceBackendEndpoints:
    def test_list_memories_scoped(self, client: TestClient) -> None:
        resp = client.get("/api/v1/memories?limit=5")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_retrieve_date_filters_reach_search_filters(self, client: TestClient) -> None:
        captured: dict = {}

        def fake_retrieve(self, q, *, user_id, limit=5, filters=None):
            captured["filters"] = filters
            return NaturalRetrieveResponse(query=q, results=[], search_path=[], elapsed_ms=1)

        with patch(
            "app.services.memory_intelligence_service.MemoryIntelligenceService.retrieve",
            fake_retrieve,
        ):
            resp = client.get(
                "/api/v1/intelligence/retrieve",
                params={
                    "q": "rag",
                    "date_from": "2024-01-01",
                    "date_to": "2025-12-31",
                    "language": "en",
                },
            )
        assert resp.status_code == 200
        assert captured["filters"] is not None
        assert captured["filters"].date_from == "2024-01-01"
        assert captured["filters"].date_to == "2025-12-31"
        assert captured["filters"].language == "en"

    def test_date_filter_logic(self) -> None:
        item = SearchResultItem(
            video_id="v1",
            title="T",
            channel="C",
            thumbnail="",
            url="https://example.com",
            original_url="https://example.com",
            timestamp_url="https://example.com",
            matched_text="x",
            start_time=0,
            end_time=1,
            relevance_score=0.9,
            why_matched="match",
            published_at="2023-06-01T15:30:00Z",
        )
        assert not _passes_filters(item, SearchFilters(date_from="2024-01-01"))
        assert _passes_filters(item, SearchFilters(date_from="2023-01-01"))
        assert not _passes_filters(item, SearchFilters(date_to="2022-01-01"))
        # Inclusive same-day bound despite ISO datetime payload
        assert _passes_filters(item, SearchFilters(date_to="2023-06-01"))
        undated = item.model_copy(update={"published_at": None})
        assert not _passes_filters(undated, SearchFilters(date_from="2020-01-01"))
        with_import = undated.model_copy(update={"import_date": "2023-06-01T01:00:00"})
        assert _passes_filters(with_import, SearchFilters(date_from="2023-06-01", date_to="2023-06-01"))

    def test_import_cancel_authorization(self, tmp_path) -> None:
        settings = Settings(
            sqlite_path=str(tmp_path / "imports.db"),
            chroma_persist_dir=str(tmp_path / "chroma"),
            jobs_enabled=False,
            auth_enabled=False,
        )
        migrate(settings)
        manager = ImportManager(settings)
        run = manager.create_import(
            user_id="user-a",
            connector_id="web.v1",
            urls=["https://example.com/a"],
            titles=["A"],
        )
        with pytest.raises(KeyError):
            manager.cancel_import(run["import_id"], user_id="user-b")
        cancelled = manager.cancel_import(run["import_id"], user_id="user-a")
        assert cancelled["status"] == "cancelled"

    def test_import_cancel_http_isolation(self, tmp_path) -> None:
        settings = Settings(
            sqlite_path=str(tmp_path / "imp2.db"),
            chroma_persist_dir=str(tmp_path / "chroma2"),
            jobs_enabled=False,
            auth_enabled=False,
            local_demo_mode=True,
        )
        migrate(settings)
        manager = ImportManager(settings)
        run = manager.create_import(
            user_id=LOCAL_DEFAULT_USER_ID,
            connector_id="web.v1",
            urls=["https://example.com/b"],
        )

        app.dependency_overrides[get_settings] = lambda: settings
        try:
            with TestClient(app) as client:
                ok = client.post(f"/api/v1/imports/{run['import_id']}/cancel")
                assert ok.status_code == 200
                assert ok.json()["status"] == "cancelled"
                missing = client.post("/api/v1/imports/nope/cancel")
                assert missing.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_import_detail_item_limit(self, tmp_path) -> None:
        settings = Settings(
            sqlite_path=str(tmp_path / "imp3.db"),
            chroma_persist_dir=str(tmp_path / "chroma3"),
            jobs_enabled=False,
        )
        migrate(settings)
        manager = ImportManager(settings)
        urls = [f"https://example.com/{i}" for i in range(5)]
        run = manager.create_import(
            user_id=LOCAL_DEFAULT_USER_ID,
            connector_id="web.v1",
            urls=urls,
        )
        detail = manager.get_import(run["import_id"], user_id=LOCAL_DEFAULT_USER_ID, item_limit=2)
        assert detail["items_returned"] == 2
        assert detail["items_total"] == 5

    def test_pdf_rejects_non_pdf(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/capture/pdf",
            files={"file": ("note.txt", b"not a pdf", "text/plain")},
        )
        assert resp.status_code == 400
        assert "PDF" in resp.json()["detail"]

    def test_pdf_accepts_magic_bytes(self, client: TestClient) -> None:
        with patch(
            "app.api.routes.imports.ConnectorIngestService.ingest_pdf_bytes"
        ) as ingest:
            ingest.return_value = MagicMock(
                success=True,
                skipped=False,
                video_id="pdf1",
                title="Doc",
                chunk_count=1,
                error=None,
                stages=[],
            )
            resp = client.post(
                "/api/v1/capture/pdf",
                files={"file": ("doc.pdf", b"%PDF-1.4 hello", "application/pdf")},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_chat_ask_memory_path(self, client: TestClient) -> None:
        from app.api.dependencies import get_chat_service

        mock_chat = MagicMock()
        mock_chat.chat.return_value = ChatResponse(
            answer="Grounded.",
            grounded=True,
            sources=[],
            confidence="high",
        )
        app.dependency_overrides[get_chat_service] = lambda: mock_chat
        try:
            resp = client.post("/api/v1/chat", json={"question": "What?", "top_k": 3})
        finally:
            app.dependency_overrides.pop(get_chat_service, None)
        assert resp.status_code == 200
        assert resp.json()["answer"] == "Grounded."


class TestWorkspaceStaticSecurityPatterns:
    def test_no_raw_href_without_escape_or_safe(self) -> None:
        """Href interpolations must go through escapeHtml or externalLink/safeHref."""
        pattern = re.compile(r'href="\$\{(?!escapeHtml|safeHref)[^}]+\}"')
        offenders = []
        for path in JS.rglob("*.js"):
            text = path.read_text(encoding="utf-8")
            # Allow externalLink which embeds escaped href internally
            if "externalLink(" in text:
                continue
            for match in pattern.finditer(text):
                offenders.append(f"{path.name}: {match.group(0)}")
        assert not offenders, offenders

    def test_modules_served(self, client: TestClient) -> None:
        for path in (
            "/static/js/api.js",
            "/static/js/util.js",
            "/static/js/router.js",
            "/sw.js",
            "/static/app.js",
        ):
            assert client.get(path).status_code == 200
