from __future__ import annotations

import inspect

import pytest

from app.config import Settings
from app.db.intelligence_store import IntelligenceStore
from app.db.postgres_topic_store import PostgresTopicStore
from app.db.schema import get_connection
from app.db.topic_privacy import delete_memory_topic_links
from app.services.privacy_service import PrivacyService


def test_sqlite_topic_link_delete_is_exact_tenant_scoped(tmp_path):
    settings = Settings(sqlite_path=str(tmp_path / "topic-delete.db"))
    store = IntelligenceStore(settings)
    with get_connection(settings) as conn:
        conn.execute(
            "INSERT INTO topic_profiles (topic_id, user_id, name, normalized_name, category, summary, memory_count, first_seen_at, last_seen_at, last_updated_at, evidence_json) VALUES (?, ?, ?, ?, ?, '', 1, ?, ?, ?, '[]')",
            ("topic-a", "tenant-a", "Topic", "topic", "other", "2026-01-01", "2026-01-01", "2026-01-01"),
        )
        conn.execute(
            "INSERT INTO topic_profiles (topic_id, user_id, name, normalized_name, category, summary, memory_count, first_seen_at, last_seen_at, last_updated_at, evidence_json) VALUES (?, ?, ?, ?, ?, '', 1, ?, ?, ?, '[]')",
            ("topic-b", "tenant-b", "Topic", "topic", "other", "2026-01-01", "2026-01-01", "2026-01-01"),
        )
        conn.execute(
            "INSERT INTO topic_memory_links (topic_id, user_id, video_id, memory_id, strength, evidence) VALUES (?, ?, ?, ?, 1.0, '')",
            ("topic-a", "tenant-a", "video-a", "memory-shared"),
        )
        conn.execute(
            "INSERT INTO topic_memory_links (topic_id, user_id, video_id, memory_id, strength, evidence) VALUES (?, ?, ?, ?, 1.0, '')",
            ("topic-b", "tenant-b", "video-b", "memory-shared"),
        )

    assert delete_memory_topic_links(store, memory_id="memory-shared", user_id="tenant-a") == 1
    with get_connection(settings) as conn:
        rows = conn.execute(
            "SELECT user_id FROM topic_memory_links WHERE memory_id = ? ORDER BY user_id",
            ("memory-shared",),
        ).fetchall()
    assert [row["user_id"] for row in rows] == ["tenant-b"]


def test_postgres_topic_link_delete_uses_exact_tenant_predicate():
    calls: list[tuple[str, tuple[str, str]]] = []

    class Cursor:
        rowcount = 1

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params):
            calls.append((" ".join(sql.split()), params))
            return Cursor()

    store = object.__new__(PostgresTopicStore)
    store._connection_factory = lambda: Connection()

    assert delete_memory_topic_links(store, memory_id="memory-1", user_id="tenant-a") == 1
    assert calls == [
        (
            "DELETE FROM topic_memory_links WHERE memory_id = %s AND user_id = %s",
            ("memory-1", "tenant-a"),
        )
    ]


def test_unknown_topic_store_fails_closed():
    with pytest.raises(TypeError, match="Unsupported topic store"):
        delete_memory_topic_links(object(), memory_id="memory-1", user_id="tenant-a")


def test_legacy_sqlite_topic_cleanup_is_removed_from_privacy_service():
    source = inspect.getsource(PrivacyService)
    assert not hasattr(PrivacyService, "_delete_sqlite_memory_rows")
    assert "topic_memory_links" not in source
