from __future__ import annotations

import hashlib
import sqlite3

import pytest

from app.config import Settings
from app.db.postgres_capture_migration import (
    migrate_captures_to_postgres,
    preview_capture_migration,
)


class _Cursor:
    def __init__(self, rowcount: int = 0) -> None:
        self.rowcount = rowcount


class _FakePostgres:
    def __init__(self) -> None:
        self.capture_ids: set[str] = set()
        self.inserted: list[tuple] = []
        self.statements: list[tuple[str, tuple | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=None):
        values = tuple(params) if params is not None else None
        self.statements.append((sql, values))
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("insert into captures"):
            capture_id = values[0]
            if capture_id in self.capture_ids:
                return _Cursor(0)
            self.capture_ids.add(capture_id)
            self.inserted.append(values)
            return _Cursor(1)
        return _Cursor(0)


def _source_db(tmp_path) -> str:
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE captures (
                capture_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                url TEXT NOT NULL,
                url_hash TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT 'web',
                status TEXT NOT NULL,
                job_id TEXT,
                stage TEXT NOT NULL DEFAULT '',
                stage_detail TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '',
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO captures VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "c2", "bob", "https://example.com/b", "hb", "B", "web", "done",
                    "j2", "done", "Saved", '{"source":"b"}', None,
                    "2026-01-02T00:00:00+00:00", "2026-01-02T00:01:00+00:00",
                ),
                (
                    "c1", "alice", "https://example.com/a", "ha", "A", "web", "queued",
                    None, "queued", "Added", '{"source":"a"}', None,
                    "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
                ),
            ],
        )
    return str(path)


def _sha256(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def test_preview_is_count_only_and_tenant_scoped(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)

    all_rows = preview_capture_migration(settings)
    alice = preview_capture_migration(settings, user_id="alice")

    assert all_rows.to_dict() == {"captures": 2, "tenants": 2}
    assert alice.to_dict() == {"captures": 1, "tenants": 1}


def test_migration_is_read_only_deterministic_and_idempotent(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)
    target = _FakePostgres()
    before = _sha256(path)

    first = migrate_captures_to_postgres(settings, connection_factory=lambda: target)
    second = migrate_captures_to_postgres(settings, connection_factory=lambda: target)

    assert _sha256(path) == before
    assert first.to_dict() == {
        "captures_seen": 2,
        "captures_inserted": 2,
        "captures_skipped_existing": 0,
    }
    assert second.to_dict() == {
        "captures_seen": 2,
        "captures_inserted": 0,
        "captures_skipped_existing": 2,
    }
    assert [(row[1], row[0]) for row in target.inserted] == [("alice", "c1"), ("bob", "c2")]
    assert all(
        "on conflict(capture_id) do nothing" in " ".join(sql.split()).lower()
        for sql, _params in target.statements
        if "insert into captures" in " ".join(sql.split()).lower()
    )


def test_migration_preserves_exact_tenant_and_full_capture_state(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)
    target = _FakePostgres()

    report = migrate_captures_to_postgres(
        settings,
        user_id="alice",
        connection_factory=lambda: target,
    )

    assert report.to_dict() == {
        "captures_seen": 1,
        "captures_inserted": 1,
        "captures_skipped_existing": 0,
    }
    row = target.inserted[0]
    assert row[0:2] == ("c1", "alice")
    assert row[6:12] == ("queued", None, "queued", "Added", '{"source":"a"}', None)


def test_blank_tenant_fails_closed(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)

    with pytest.raises(ValueError, match="user_id must not be blank"):
        preview_capture_migration(settings, user_id="   ")


def test_missing_sqlite_source_fails_without_creating_a_database(tmp_path):
    path = tmp_path / "missing.db"
    settings = Settings(sqlite_path=str(path))

    with pytest.raises(FileNotFoundError):
        preview_capture_migration(settings)

    assert not path.exists()
