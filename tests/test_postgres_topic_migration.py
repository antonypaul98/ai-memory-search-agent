from __future__ import annotations

import hashlib
import sqlite3

import pytest

from app.config import Settings
from app.db.postgres_topic_migration import migrate_topics_to_postgres, preview_topic_migration


class _Cursor:
    def __init__(self, rowcount: int = 0) -> None:
        self.rowcount = rowcount


class _FakePostgres:
    def __init__(self) -> None:
        self.topic_ids: set[str] = set()
        self.topic_keys: set[tuple[str, str]] = set()
        self.link_keys: set[tuple[str, str]] = set()
        self.topic_rows: list[tuple] = []
        self.link_rows: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=None):
        values = tuple(params) if params is not None else ()
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("insert into topic_profiles"):
            topic_id, user_id, _, normalized_name = values[:4]
            key = (user_id, normalized_name)
            if topic_id in self.topic_ids or key in self.topic_keys:
                return _Cursor(0)
            self.topic_ids.add(topic_id)
            self.topic_keys.add(key)
            self.topic_rows.append(values)
            return _Cursor(1)
        if normalized.startswith("insert into topic_memory_links"):
            topic_id, user_id, video_id = values[:3]
            key = (topic_id, video_id)
            if topic_id not in self.topic_ids:
                raise AssertionError("link inserted without topic")
            if key in self.link_keys:
                return _Cursor(0)
            self.link_keys.add(key)
            self.link_rows.append(values)
            return _Cursor(1)
        return _Cursor(0)


def _source_db(tmp_path) -> str:
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE topic_profiles (
            topic_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            category TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            memory_count INTEGER NOT NULL DEFAULT 0,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            last_updated_at TEXT NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '[]',
            UNIQUE(user_id, normalized_name)
        );
        CREATE TABLE topic_memory_links (
            topic_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            video_id TEXT NOT NULL,
            memory_id TEXT,
            strength REAL NOT NULL DEFAULT 1.0,
            evidence TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(topic_id, video_id)
        );
        """)
        conn.executemany(
            "INSERT INTO topic_profiles VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("topic_b", "bob", "RAG", "rag", "technology", "B", 1, "2026-01-02", "2026-01-02", "2026-01-02", '["ev-b"]'),
                ("topic_a", "alice", "Python", "python", "language", "A", 1, "2026-01-01", "2026-01-01", "2026-01-01", '["ev-a"]'),
            ],
        )
        conn.executemany(
            "INSERT INTO topic_memory_links VALUES (?,?,?,?,?,?)",
            [
                ("topic_b", "bob", "vid-b", "mem-b", 0.8, "ev-b"),
                ("topic_a", "alice", "vid-a", "mem-a", 1.0, "ev-a"),
            ],
        )
    return str(path)


def _sha256(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def test_preview_is_count_only_and_tenant_scoped(tmp_path):
    settings = Settings(sqlite_path=_source_db(tmp_path))
    assert preview_topic_migration(settings).to_dict() == {"topics": 2, "links": 2, "tenants": 2}
    assert preview_topic_migration(settings, user_id="alice").to_dict() == {"topics": 1, "links": 1, "tenants": 1}


def test_migration_is_read_only_deterministic_and_idempotent(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)
    target = _FakePostgres()
    before = _sha256(path)

    first = migrate_topics_to_postgres(settings, connection_factory=lambda: target)
    second = migrate_topics_to_postgres(settings, connection_factory=lambda: target)

    assert _sha256(path) == before
    assert first.to_dict() == {
        "topics_seen": 2,
        "topics_inserted": 2,
        "topics_skipped_existing": 0,
        "links_seen": 2,
        "links_inserted": 2,
        "links_skipped_existing": 0,
    }
    assert second.to_dict() == {
        "topics_seen": 2,
        "topics_inserted": 0,
        "topics_skipped_existing": 2,
        "links_seen": 2,
        "links_inserted": 0,
        "links_skipped_existing": 2,
    }
    assert [(row[1], row[3]) for row in target.topic_rows] == [("alice", "python"), ("bob", "rag")]
    assert [(row[1], row[2]) for row in target.link_rows] == [("alice", "vid-a"), ("bob", "vid-b")]


def test_migration_rejects_link_with_unselected_or_mismatched_owner(tmp_path):
    path = _source_db(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE topic_memory_links SET user_id = 'mallory' WHERE topic_id = 'topic_a'")
    settings = Settings(sqlite_path=path)
    target = _FakePostgres()
    with pytest.raises(ValueError, match="ownership"):
        migrate_topics_to_postgres(settings, connection_factory=lambda: target)
    assert target.topic_rows == []
    assert target.link_rows == []


def test_blank_tenant_fails_closed(tmp_path):
    settings = Settings(sqlite_path=_source_db(tmp_path))
    with pytest.raises(ValueError, match="user_id must not be blank"):
        preview_topic_migration(settings, user_id=" ")


def test_missing_source_does_not_create_database(tmp_path):
    path = tmp_path / "missing.db"
    settings = Settings(sqlite_path=str(path))
    with pytest.raises(FileNotFoundError):
        preview_topic_migration(settings)
    assert not path.exists()
