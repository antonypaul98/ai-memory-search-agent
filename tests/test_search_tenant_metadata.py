"""Regression tests for tenant-scoped search reflection and usage metadata."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.config import Settings
from app.db.video_registry import VideoRegistry
from app.models.reflection import ReflectionInput, SaveReason
from app.services.search_service import _to_search_result_item


def test_search_result_uses_current_tenant_reflection_and_usage(tmp_path) -> None:
    settings = Settings(sqlite_path=str(tmp_path / "tenant-search.db"))
    registry = VideoRegistry(settings)

    registry.upsert_video(
        video_id="shared-video",
        url="https://www.youtube.com/watch?v=shared-video",
        title="Shared public video",
        channel="Public Channel",
        reflection=ReflectionInput(
            save_reason=SaveReason.PROJECT,
            goal="private goal A",
            reflection_note="private note A",
        ),
        user_id="user-a",
    )
    registry.upsert_video(
        video_id="shared-video",
        url="https://www.youtube.com/watch?v=shared-video",
        title="Shared public video",
        channel="Public Channel",
        reflection=ReflectionInput(
            save_reason=SaveReason.REFERENCE,
            goal="private goal B",
            reflection_note="private note B",
        ),
        user_id="user-b",
    )
    registry.record_view("shared-video", user_id="user-a")
    registry.record_view("shared-video", user_id="user-a")
    registry.record_view("shared-video", user_id="user-b")

    hit = {
        "video_id": "shared-video",
        "url": "https://www.youtube.com/watch?v=shared-video",
        "title": "Shared public video",
        "channel": "Public Channel",
        "thumbnail": "",
        "duration": 60.0,
        "matched_text": "public transcript evidence",
        "start_time": 0.0,
        "end_time": 5.0,
        "relevance_score": 0.9,
    }
    yt_store = MagicMock()
    yt_store.get.return_value = None

    item = _to_search_result_item(
        hit=hit,
        query="reference",
        registry=registry,
        yt_store=yt_store,
        user_id="user-b",
    )

    assert item.current_goal == "private goal B"
    assert item.reflection.reflection_note == "private note B"
    assert item.save_reason == "reference"
    assert item.usage.view_count == 1
    assert "private goal A" not in item.reflection.reflection_message
    yt_store.get.assert_called_once_with("shared-video", user_id="user-b")


def test_search_tracking_updates_only_current_tenant(tmp_path) -> None:
    settings = Settings(sqlite_path=str(tmp_path / "tenant-tracking.db"))
    registry = VideoRegistry(settings)
    for user in ("user-a", "user-b"):
        registry.upsert_video(
            video_id="shared-video",
            url="https://www.youtube.com/watch?v=shared-video",
            title="Shared public video",
            channel="Public Channel",
            user_id=user,
        )

    registry.record_search(["shared-video"], user_id="user-b")

    assert registry.get_usage("shared-video", user_id="user-a").search_count == 0
    assert registry.get_usage("shared-video", user_id="user-b").search_count == 1
