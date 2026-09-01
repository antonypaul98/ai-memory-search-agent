from __future__ import annotations

import sqlite3

import pytest

from app.config import Settings
from app.db.postgres_fts_migration import (
    migrate_lexical_to_postgres,
    preview_lexical_migration,
)


class _Cursor:
    def __init__(self, rowcount=0, rows=None):
        self.rowcount = rowcount
        self._rows = rows or []

    def fetchall(self):
        return list(self._rows)


class _Connection:
    def __init__(self, existing=None):
        self.calls = []
        self.existing = existing if existing is not None else set()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())
        packed = tuple(params) if params is not None else None
        self.calls.append((normalized, packed))
        if normalized.startswith("INSERT INTO memory_fts_documents"):
            key = (packed[0], packed[3])
            if key in self.existing:
                return _Cursor(rowcount=0)
            self.existing.add(key)
            return _Cursor(rowcount=1)
        return _Cursor()


class _Factory:
    def __init__(self):
        self.connections = []
        self.existing = set()

    def __call__(self):
        conn = _Connection(self.existing)
        self.connections.append(conn)
        return conn

    @property
    def calls(self):
        return [call for conn in self.connections for call in conn.calls]


def _source(tmp_path):
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE VIRTUAL TABLE memory_fts USING fts5(video_id, level, doc_id, title, body)"
        )
        conn.executemany(
            "INSERT INTO memory_fts(video_id, level, doc_id, title, body) VALUES (?, ?, ?, ?, ?)",
            [
                ("video-b", "evidence", "doc-b", "B", "second memory"),
                ("video-a", "section", "doc-a", "A", "first memory"),
            ],
        )
    return path


def test_preview_is_count_only_and_does_not_contact_postgres(tmp_path):
    path = _source(tmp_path)
    settings = Settings(sqlite_path=str(path))

    preview = preview_lexical_migration(settings, user_id="tenant-a")

    assert preview.to_dict() == {"documents": 2, "tenant": "tenant-a"}


def test_migration_requires_explicit_tenant_because_source_has_no_user_id(tmp_path):
    path = _source(tmp_path)
    settings = Settings(sqlite_path=str(path))

    with pytest.raises(ValueError, match="legacy SQLite FTS table has no tenant identity"):
        preview_lexical_migration(settings, user_id="   ")


def test_migration_is_deterministic_tenant_scoped_and_idempotent(tmp_path):
    path = _source(tmp_path)
    settings = Settings(sqlite_path=str(path))
    factory = _Factory()

    first = migrate_lexical_to_postgres(
        settings,
        user_id="tenant-a",
        connection_factory=factory,
    )
    second = migrate_lexical_to_postgres(
        settings,
        user_id="tenant-a",
        connection_factory=factory,
    )

    assert first.documents_seen == 2
    assert first.documents_inserted == 2
    assert first.documents_skipped_existing == 0
    assert second.documents_seen == 2
    assert second.documents_inserted == 0
    assert second.documents_skipped_existing == 2

    inserts = [
        params
        for sql, params in factory.calls
        if sql.startswith("INSERT INTO memory_fts_documents")
    ]
    assert [params[3] for params in inserts[:2]] == ["doc-a", "doc-b"]
    assert all(params[0] == "tenant-a" for params in inserts)
    assert any("ON CONFLICT(user_id, doc_id) DO NOTHING" in sql for sql, _ in factory.calls)


def test_source_is_opened_read_only(tmp_path):
    path = _source(tmp_path)
    settings = Settings(sqlite_path=str(path))
    factory = _Factory()

    before = path.read_bytes()
    migrate_lexical_to_postgres(settings, user_id="tenant-a", connection_factory=factory)
    after = path.read_bytes()

    assert after == before


def test_missing_source_fails_closed_without_creating_database(tmp_path):
    path = tmp_path / "missing.db"
    settings = Settings(sqlite_path=str(path))

    with pytest.raises(FileNotFoundError, match="migration source does not exist"):
        preview_lexical_migration(settings, user_id="tenant-a")

    assert not path.exists()
