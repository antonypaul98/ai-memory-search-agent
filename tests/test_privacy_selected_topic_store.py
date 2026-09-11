from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import privacy_service as privacy_module
from app.services.privacy_service import PrivacyService


def _topic_payload(topic_id: str, user_id: str) -> SimpleNamespace:
    payload = {
        "topic_id": topic_id,
        "user_id": user_id,
        "name": "Postgres",
        "normalized_name": "postgres",
        "category": "technology",
        "summary": "Selected-store topic",
        "memory_count": 1,
        "first_seen_at": "2026-09-11T10:00:00+00:00",
        "last_seen_at": "2026-09-11T10:00:00+00:00",
        "last_updated_at": "2026-09-11T10:00:00+00:00",
        "evidence": ["memory-a"],
        "video_ids": ["video-a"],
    }
    return SimpleNamespace(model_dump=lambda **kwargs: dict(payload))


def test_privacy_export_routes_topics_through_selected_store_without_sqlite_read(monkeypatch):
    service = PrivacyService.__new__(PrivacyService)
    service._settings = SimpleNamespace()
    service._auth_store = MagicMock()
    service._auth_store.get_user_for_export.return_value = {
        "user_id": "tenant-a",
        "email": "a@example.test",
        "display_name": "A",
        "created_at": "now",
    }
    service._memory_store = MagicMock()
    service._memory_store.list_recent.return_value = []
    service._youtube_store = MagicMock()
    service._youtube_store.list_for_user.return_value = []
    service._capture_store = MagicMock()
    service._capture_store.list_for_user.return_value = []
    service._bookmark_store = MagicMock()
    service._bookmark_store.list_for_user.return_value = []
    service._registry = MagicMock()
    service._registry.list_videos.return_value = []
    service._topic_store = MagicMock()
    service._topic_store.list_topics.return_value = [_topic_payload("topic-a", "tenant-a")]

    jobs_reader = MagicMock(return_value=[])
    monkeypatch.setattr(privacy_module, "list_jobs_for_user", jobs_reader)

    def _forbid_sqlite(*args, **kwargs):
        raise AssertionError("privacy topic export must not open the legacy SQLite connection")

    monkeypatch.setattr(privacy_module, "get_connection", _forbid_sqlite)

    payload = service.export_user_data(user_id="tenant-a")

    service._topic_store.list_topics.assert_called_once_with("tenant-a", limit=500)
    assert payload["topics"] == [
        {
            "topic_id": "topic-a",
            "user_id": "tenant-a",
            "name": "Postgres",
            "normalized_name": "postgres",
            "category": "technology",
            "summary": "Selected-store topic",
            "memory_count": 1,
            "first_seen_at": "2026-09-11T10:00:00+00:00",
            "last_seen_at": "2026-09-11T10:00:00+00:00",
            "last_updated_at": "2026-09-11T10:00:00+00:00",
            "evidence": ["memory-a"],
            "video_ids": ["video-a"],
        }
    ]
