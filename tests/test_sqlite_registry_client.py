from __future__ import annotations

import sqlite3

import pytest

from app.db.sqlite_client import SQLiteRegistryClient
from app.db.video_registry import VideoRegistry


def _seed(registry: VideoRegistry, *, user_id: str, video_id: str, title: str) -> None:
    registry.upsert_video(
        video_id=video_id,
        url=f"https://www.youtube.com/watch?v={video_id}",
        title=title,
        channel="Example",
        user_id=user_id,
    )


def test_list_items_is_tenant_scoped(test_settings) -> None:
    registry = VideoRegistry(test_settings)
    _seed(registry, user_id="alice", video_id="a1", title="Alice memory")
    _seed(registry, user_id="bob", video_id="b1", title="Bob memory")

    client = SQLiteRegistryClient(test_settings)

    alice = client.list_items(user_id="alice")
    bob = client.list_items(user_id="bob")

    assert [item.video_id for item in alice] == ["a1"]
    assert [item.title for item in alice] == ["Alice memory"]
    assert [item.video_id for item in bob] == ["b1"]


def test_list_items_supports_deterministic_pagination(test_settings) -> None:
    registry = VideoRegistry(test_settings)
    _seed(registry, user_id="alice", video_id="b", title="B")
    _seed(registry, user_id="alice", video_id="a", title="A")

    # Make saved_at identical so the documented video_id tie-breaker is exercised.
    with sqlite3.connect(test_settings.sqlite_path) as conn:
        conn.execute(
            "UPDATE video_registry SET saved_at = ? WHERE user_id = ?",
            ("2026-01-01T00:00:00+00:00", "alice"),
        )

    client = SQLiteRegistryClient(test_settings)

    assert [item.video_id for item in client.list_items(user_id="alice", limit=1)] == ["a"]
    assert [item.video_id for item in client.list_items(user_id="alice", limit=1, offset=1)] == ["b"]


@pytest.mark.parametrize(
    ("limit", "offset"),
    [(0, 0), (1001, 0), (1, -1)],
)
def test_list_items_rejects_invalid_pagination(test_settings, limit: int, offset: int) -> None:
    client = SQLiteRegistryClient(test_settings)

    with pytest.raises(ValueError):
        client.list_items(user_id="alice", limit=limit, offset=offset)


def test_delete_item_is_tenant_scoped_and_reports_presence(test_settings) -> None:
    registry = VideoRegistry(test_settings)
    _seed(registry, user_id="alice", video_id="shared", title="Alice")
    _seed(registry, user_id="bob", video_id="shared", title="Bob")

    client = SQLiteRegistryClient(test_settings)

    assert client.delete_item("shared", user_id="alice") is True
    assert client.delete_item("shared", user_id="alice") is False
    assert client.list_items(user_id="alice") == []
    assert [item.title for item in client.list_items(user_id="bob")] == ["Bob"]


def test_delete_item_removes_matching_reflection_only(test_settings) -> None:
    registry = VideoRegistry(test_settings)
    _seed(registry, user_id="alice", video_id="v1", title="One")
    _seed(registry, user_id="bob", video_id="v1", title="Other tenant")

    with sqlite3.connect(test_settings.sqlite_path) as conn:
        conn.execute(
            """
            INSERT INTO video_reflection (user_id, video_id, save_reason, goal)
            VALUES (?, ?, ?, ?)
            """,
            ("alice", "v1", "learn", "goal-a"),
        )
        conn.execute(
            """
            INSERT INTO video_reflection (user_id, video_id, save_reason, goal)
            VALUES (?, ?, ?, ?)
            """,
            ("bob", "v1", "learn", "goal-b"),
        )

    client = SQLiteRegistryClient(test_settings)
    assert client.delete_item("v1", user_id="alice") is True

    with sqlite3.connect(test_settings.sqlite_path) as conn:
        alice = conn.execute(
            "SELECT 1 FROM video_reflection WHERE user_id = ? AND video_id = ?",
            ("alice", "v1"),
        ).fetchone()
        bob = conn.execute(
            "SELECT 1 FROM video_reflection WHERE user_id = ? AND video_id = ?",
            ("bob", "v1"),
        ).fetchone()

    assert alice is None
    assert bob is not None


def test_delete_item_requires_nonempty_id(test_settings) -> None:
    client = SQLiteRegistryClient(test_settings)

    with pytest.raises(ValueError, match="video_id is required"):
        client.delete_item("", user_id="alice")
