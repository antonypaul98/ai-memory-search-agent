from __future__ import annotations

import hashlib
import sqlite3

import pytest

from app.config import Settings
from app.db.postgres_video_registry_migration import (
    migrate_video_registry_to_postgres,
    preview_video_registry_migration,
)


class _Cursor:
    def __init__(self, rowcount: int = 0) -> None:
        self.rowcount = rowcount


class _FakePostgres:
    def __init__(self) -> None:
        self.video_keys: set[tuple[str, str]] = set()
        self.reflection_keys: set[tuple[str, str]] = set()
        self.statements: list[tuple[str, tuple | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=None):
        values = tuple(params) if params is not None else None
        self.statements.append((sql, values))
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("insert into video_registry"):
            key = (values[0], values[1])
            if key in self.video_keys:
                return _Cursor(0)
            self.video_keys.add(key)
            return _Cursor(1)
        if normalized.startswith("insert into video_reflection"):
            key = (values[0], values[1])
            if key in self.reflection_keys:
                return _Cursor(0)
            self.reflection_keys.add(key)
            return _Cursor(1)
        return _Cursor(0)


def _source_db(tmp_path) -> str:
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE video_registry (
                user_id TEXT NOT NULL,
                video_id TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                channel TEXT NOT NULL,
                saved_at TEXT NOT NULL,
                last_viewed TEXT,
                view_count INTEGER NOT NULL,
                search_count INTEGER NOT NULL,
                last_searched TEXT,
                helpful_count INTEGER NOT NULL,
                not_helpful_count INTEGER NOT NULL,
                PRIMARY KEY (user_id, video_id)
            );
            CREATE TABLE video_reflection (
                user_id TEXT NOT NULL,
                video_id TEXT NOT NULL,
                save_reason TEXT NOT NULL,
                goal TEXT NOT NULL,
                reflection_note TEXT NOT NULL,
                recommendations_enabled INTEGER NOT NULL,
                preferred_creator_only INTEGER NOT NULL,
                allow_other_creators INTEGER NOT NULL,
                difficulty TEXT NOT NULL,
                preferred_style TEXT NOT NULL,
                PRIMARY KEY (user_id, video_id)
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO video_registry VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("alice", "v1", "https://youtu.be/v1", "One", "A", "2026-01-01T00:00:00+00:00", None, 2, 3, None, 1, 0),
                ("bob", "v1", "https://youtu.be/v1", "One", "A", "2026-01-02T00:00:00+00:00", None, 4, 5, None, 0, 2),
            ],
        )
        conn.execute(
            """
            INSERT INTO video_reflection VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("alice", "v1", "learn", "goal", "note", 1, 0, 1, "beginner", "practical"),
        )
    return str(path)


def _sha256(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def test_preview_is_count_only_and_tenant_scoped(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)

    all_rows = preview_video_registry_migration(settings)
    alice = preview_video_registry_migration(settings, user_id="alice")

    assert all_rows.to_dict() == {"videos": 2, "reflections": 1, "tenants": 2}
    assert alice.to_dict() == {"videos": 1, "reflections": 1, "tenants": 1}


def test_migration_is_read_only_at_source_and_idempotent_at_target(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)
    target = _FakePostgres()
    before = _sha256(path)

    first = migrate_video_registry_to_postgres(
        settings,
        connection_factory=lambda: target,
    )
    second = migrate_video_registry_to_postgres(
        settings,
        connection_factory=lambda: target,
    )

    assert _sha256(path) == before
    assert first.to_dict() == {
        "videos_seen": 2,
        "videos_inserted": 2,
        "videos_skipped_existing": 0,
        "reflections_seen": 1,
        "reflections_inserted": 1,
        "reflections_skipped_existing": 0,
    }
    assert second.to_dict() == {
        "videos_seen": 2,
        "videos_inserted": 0,
        "videos_skipped_existing": 2,
        "reflections_seen": 1,
        "reflections_inserted": 0,
        "reflections_skipped_existing": 1,
    }
    assert all(
        "on conflict(user_id, video_id) do nothing" in " ".join(sql.split()).lower()
        for sql, _params in target.statements
        if "insert into video_" in " ".join(sql.split()).lower()
    )


def test_migration_keeps_tenants_separate_and_maps_reflection_booleans(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)
    target = _FakePostgres()

    report = migrate_video_registry_to_postgres(
        settings,
        user_id="alice",
        connection_factory=lambda: target,
    )

    assert report.videos_seen == 1
    assert target.video_keys == {("alice", "v1")}
    assert target.reflection_keys == {("alice", "v1")}
    reflection_params = next(
        params
        for sql, params in target.statements
        if "insert into video_reflection" in " ".join(sql.split()).lower()
    )
    assert reflection_params[5:8] == (True, False, True)


def test_missing_sqlite_source_fails_without_creating_a_database(tmp_path):
    path = tmp_path / "missing.db"
    settings = Settings(sqlite_path=str(path))

    with pytest.raises(FileNotFoundError):
        preview_video_registry_migration(settings)

    assert not path.exists()
