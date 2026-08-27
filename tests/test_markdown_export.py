"""Regression tests for C-08 portable Markdown export."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.services.privacy_service import dump_export_markdown


ROOT = Path(__file__).resolve().parents[1]


def test_markdown_export_preserves_human_summary_and_complete_records() -> None:
    payload = {
        "export_version": 1,
        "exported_at": "2026-08-27T12:00:00+00:00",
        "user": {"user_id": "u1", "display_name": "Demo User"},
        "memories": [
            {
                "memory_id": "m1",
                "source_type": "web",
                "external_id": "https://example.com/a",
                "canonical_url": "https://example.com/a",
                "title": "RAG [notes]",
                "source_author": "Author",
                "lifecycle_state": "trusted",
                "verification_status": "verified",
                "created_at": "2026-08-20T00:00:00+00:00",
                "updated_at": "2026-08-21T00:00:00+00:00",
                "metadata": {
                    "save_reason": "Use in memory project",
                    "user_goal": "Learn RAG",
                    "custom_private_field": "preserve-me",
                },
                "trust": {"tier": "trusted", "overall": 0.91},
            }
        ],
        "youtube_memories": [],
        "captures": [{"capture_id": "c1", "status": "completed"}],
        "browser_bookmarks": [],
        "jobs": [],
        "topics": [{"topic_id": "rag"}],
        "video_registry": [],
    }

    text = dump_export_markdown(payload)

    assert text.startswith("# AI Memory Export\n")
    assert "### RAG \\[notes\\]" in text
    assert "- Why saved: Use in memory project" in text
    assert "- Goal: Learn RAG" in text
    assert "- Trust: trusted (0.91)" in text
    # Raw exported records remain present so the adapter does not silently lose fields.
    assert '"custom_private_field": "preserve-me"' in text
    assert '"capture_id": "c1"' in text
    assert '"topic_id": "rag"' in text


def test_markdown_export_endpoint_and_download_headers(client: TestClient) -> None:
    response = client.get("/api/v1/privacy/export?format=markdown&download=true")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.headers["content-disposition"].endswith('.md"')
    assert response.text.startswith("# AI Memory Export")


def test_json_export_remains_default(client: TestClient) -> None:
    response = client.get("/api/v1/privacy/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["export_version"] == 1


def test_invalid_export_format_is_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/privacy/export?format=html")

    assert response.status_code == 422


def test_settings_exposes_authenticated_markdown_download() -> None:
    settings_js = (ROOT / "app/static/js/views/settings.js").read_text(encoding="utf-8")

    assert 'id="set-export-markdown"' in settings_js
    assert 'privacy/export?format=markdown&download=true' in settings_js
    assert 'headers.Authorization = `Bearer ${token}`' in settings_js
    assert 'ai-memory-export-${Date.now()}.md' in settings_js
