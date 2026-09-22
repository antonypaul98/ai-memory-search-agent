from __future__ import annotations
from tests.postgres_fence_fakes import is_fence_query, UnfencedCursor

import hashlib
import sqlite3

import pytest

from app.config import Settings
from app.db.postgres_review_schedule_migration import (
    migrate_review_schedules_to_postgres,
    preview_review_schedule_migration,
)


class _Cursor:
    def __init__(self, rowcount: int = 0) -> None:
        self.rowcount = rowcount


class _FakePostgres:
    def __init__(self) -> None:
        self.keys: set[tuple[str, str]] = set()
        self.inserted: list[tuple] = []
        self.statements: list[tuple[str, tuple | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=None):
        if is_fence_query(sql):
            return UnfencedCursor()
        values = tuple(params) if params is not None else None
        self.statements.append((sql, values))
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("select 1 from video_registry"):
            return type("OwnershipCursor", (), {"fetchone": lambda self: {"owned": 1}})()
        if normalized.startswith("insert into memory_review_schedule"):
            key = (values[0], values[1])
            if key in self.keys:
                return _Cursor(0)
            self.keys.add(key)
            self.inserted.append(values)
            return _Cursor(1)
        return _Cursor(0)


def _source_db(tmp_path) -> str:
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE video_registry(user_id TEXT, video_id TEXT);
            INSERT INTO video_registry VALUES ('alice', 'shared-video'), ('bob', 'shared-video');
            CREATE TABLE memory_review_schedule (
                user_id TEXT NOT NULL,
                video_id TEXT NOT NULL,
                last_reviewed_at TEXT NOT NULL,
                next_review_at TEXT NOT NULL,
                review_count INTEGER NOT NULL DEFAULT 0,
                last_result TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, video_id)
            );
            """
        )
        conn.executemany(
            "INSERT INTO memory_review_schedule VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "bob", "shared-video", "2026-01-02T00:00:00+00:00",
                    "2026-01-09T00:00:00+00:00", 4, "good",
                    "2026-01-02T00:00:00+00:00",
                ),
                (
                    "alice", "shared-video", "2026-01-01T00:00:00+00:00",
                    "2026-01-15T00:00:00+00:00", 7, "easy",
                    "2026-01-01T00:00:00+00:00",
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

    assert preview_review_schedule_migration(settings).to_dict() == {
        "schedules": 2,
        "tenants": 2,
    }
    assert preview_review_schedule_migration(settings, user_id="alice").to_dict() == {
        "schedules": 1,
        "tenants": 1,
    }


def test_migration_is_read_only_deterministic_and_idempotent(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)
    target = _FakePostgres()
    before = _sha256(path)

    first = migrate_review_schedules_to_postgres(settings, connection_factory=lambda: target)
    second = migrate_review_schedules_to_postgres(settings, connection_factory=lambda: target)

    assert _sha256(path) == before
    assert first.to_dict() == {
        "schedules_seen": 2,
        "schedules_inserted": 2,
        "schedules_skipped_existing": 0,
    }
    assert second.to_dict() == {
        "schedules_seen": 2,
        "schedules_inserted": 0,
        "schedules_skipped_existing": 2,
    }
    assert [(row[0], row[1]) for row in target.inserted] == [
        ("alice", "shared-video"),
        ("bob", "shared-video"),
    ]
    assert all(
        "on conflict(user_id, video_id) do nothing" in " ".join(sql.split()).lower()
        for sql, _params in target.statements
        if "insert into memory_review_schedule" in " ".join(sql.split()).lower()
    )


def test_existing_target_row_remains_authoritative(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)
    target = _FakePostgres()
    target.keys.add(("alice", "shared-video"))

    report = migrate_review_schedules_to_postgres(settings, connection_factory=lambda: target)

    assert report.to_dict() == {
        "schedules_seen": 2,
        "schedules_inserted": 1,
        "schedules_skipped_existing": 1,
    }
    assert [(row[0], row[1]) for row in target.inserted] == [("bob", "shared-video")]


def test_exact_tenant_filter_preserves_shared_video_isolation(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)
    target = _FakePostgres()

    report = migrate_review_schedules_to_postgres(
        settings, user_id="alice", connection_factory=lambda: target
    )

    assert report.to_dict() == {
        "schedules_seen": 1,
        "schedules_inserted": 1,
        "schedules_skipped_existing": 0,
    }
    assert target.inserted[0] == (
        "alice", "shared-video", "2026-01-01T00:00:00+00:00",
        "2026-01-15T00:00:00+00:00", 7, "easy",
        "2026-01-01T00:00:00+00:00",
    )


def test_blank_tenant_fails_closed(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)
    with pytest.raises(ValueError, match="user_id must not be blank"):
        preview_review_schedule_migration(settings, user_id="   ")


def test_missing_sqlite_source_does_not_create_database(tmp_path):
    path = tmp_path / "missing.db"
    settings = Settings(sqlite_path=str(path))
    with pytest.raises(FileNotFoundError):
        preview_review_schedule_migration(settings)
    assert not path.exists()
