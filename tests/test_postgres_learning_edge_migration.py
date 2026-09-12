from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from app.config import Settings
from app.db.postgres_learning_edge_migration import (
    migrate_learning_edges_to_postgres,
    preview_learning_edge_migration,
)


class _Cursor:
    def __init__(self, rowcount: int = 0) -> None:
        self.rowcount = rowcount


class _FakePostgres:
    def __init__(self) -> None:
        self.edge_ids: set[str] = set()
        self.edge_keys: set[tuple[str, str, str, str]] = set()
        self.edge_rows: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=None):
        values = tuple(params) if params is not None else ()
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("insert into learning_edges"):
            edge_id, user_id, source_video_id, target_video_id, relation = values[:5]
            key = (user_id, source_video_id, target_video_id, relation)
            if edge_id in self.edge_ids or key in self.edge_keys:
                return _Cursor(0)
            self.edge_ids.add(edge_id)
            self.edge_keys.add(key)
            self.edge_rows.append(values)
            return _Cursor(1)
        return _Cursor(0)


def _source_db(tmp_path) -> str:
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE learning_edges (
            edge_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            source_video_id TEXT NOT NULL,
            target_video_id TEXT NOT NULL,
            relation TEXT NOT NULL,
            strength REAL NOT NULL DEFAULT 0.5,
            evidence TEXT NOT NULL DEFAULT '',
            evidence_refs_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            UNIQUE(user_id, source_video_id, target_video_id, relation)
        );
        """)
        conn.executemany(
            "INSERT INTO learning_edges VALUES (?,?,?,?,?,?,?,?,?)",
            [
                ("edge_b", "bob", "vid-b1", "vid-b2", "expands", 0.8, "B", '["ev-b"]', "2026-01-02"),
                ("edge_a", "alice", "vid-a1", "vid-a2", "same_topic", 0.9, "A", '["ev-a"]', "2026-01-01"),
            ],
        )
    return str(path)


def _sha256(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def test_preview_is_count_only_and_tenant_scoped(tmp_path):
    settings = Settings(sqlite_path=_source_db(tmp_path))
    assert preview_learning_edge_migration(settings).to_dict() == {"edges": 2, "tenants": 2}
    assert preview_learning_edge_migration(settings, user_id="alice").to_dict() == {
        "edges": 1,
        "tenants": 1,
    }


def test_migration_is_read_only_deterministic_and_idempotent(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)
    target = _FakePostgres()
    before = _sha256(path)

    first = migrate_learning_edges_to_postgres(settings, connection_factory=lambda: target)
    second = migrate_learning_edges_to_postgres(settings, connection_factory=lambda: target)

    assert _sha256(path) == before
    assert first.to_dict() == {
        "edges_seen": 2,
        "edges_inserted": 2,
        "edges_skipped_existing": 0,
    }
    assert second.to_dict() == {
        "edges_seen": 2,
        "edges_inserted": 0,
        "edges_skipped_existing": 2,
    }
    assert [(row[1], row[2], row[3], row[4]) for row in target.edge_rows] == [
        ("alice", "vid-a1", "vid-a2", "same_topic"),
        ("bob", "vid-b1", "vid-b2", "expands"),
    ]


def test_tenant_scoped_migration_never_copies_other_tenant(tmp_path):
    settings = Settings(sqlite_path=_source_db(tmp_path))
    target = _FakePostgres()
    report = migrate_learning_edges_to_postgres(
        settings, user_id="alice", connection_factory=lambda: target
    )
    assert report.edges_seen == 1
    assert [row[1] for row in target.edge_rows] == ["alice"]


def test_invalid_source_is_rejected_before_target_mutation(tmp_path):
    path = _source_db(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE learning_edges SET evidence_refs_json = ? WHERE edge_id = ?",
            (json.dumps({"not": "a list"}), "edge_a"),
        )
    target = _FakePostgres()
    with pytest.raises(ValueError, match="list of strings"):
        migrate_learning_edges_to_postgres(
            Settings(sqlite_path=path), connection_factory=lambda: target
        )
    assert target.edge_rows == []


def test_blank_tenant_fails_closed(tmp_path):
    settings = Settings(sqlite_path=_source_db(tmp_path))
    with pytest.raises(ValueError, match="user_id must not be blank"):
        preview_learning_edge_migration(settings, user_id=" ")


def test_missing_source_does_not_create_database(tmp_path):
    path = tmp_path / "missing.db"
    settings = Settings(sqlite_path=str(path))
    with pytest.raises(FileNotFoundError):
        preview_learning_edge_migration(settings)
    assert not path.exists()
