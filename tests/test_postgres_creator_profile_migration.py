from __future__ import annotations

import hashlib
import sqlite3

import pytest

from app.config import Settings
from app.db.postgres_creator_profile_migration import (
    migrate_creator_profiles_to_postgres,
    preview_creator_profile_migration,
)


class _Cursor:
    def __init__(self, rowcount: int = 0) -> None:
        self.rowcount = rowcount

    def fetchone(self):
        return None


class _FakePostgres:
    def __init__(self) -> None:
        self.creator_ids: set[str] = set()
        self.creator_keys: set[tuple[str, str]] = set()
        self.creator_rows: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=None):
        values = tuple(params) if params is not None else ()
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("insert into creator_profiles"):
            creator_id, user_id, _name, normalized_name = values[:4]
            key = (user_id, normalized_name)
            if creator_id in self.creator_ids or key in self.creator_keys:
                return _Cursor(0)
            self.creator_ids.add(creator_id)
            self.creator_keys.add(key)
            self.creator_rows.append(values)
            return _Cursor(1)
        return _Cursor(0)


def _source_db(tmp_path) -> str:
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE creator_profiles (
            creator_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            channel_id TEXT NOT NULL DEFAULT '',
            video_count INTEGER NOT NULL DEFAULT 0,
            topics_json TEXT NOT NULL DEFAULT '[]',
            total_duration_sec REAL NOT NULL DEFAULT 0,
            avg_duration_sec REAL NOT NULL DEFAULT 0,
            beginner_count INTEGER NOT NULL DEFAULT 0,
            advanced_count INTEGER NOT NULL DEFAULT 0,
            view_count INTEGER NOT NULL DEFAULT 0,
            helpful_count INTEGER NOT NULL DEFAULT 0,
            related_creators_json TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, normalized_name)
        );
        """)
        conn.executemany(
            "INSERT INTO creator_profiles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("creator_b", "bob", "Bob Dev", "bob dev", "ch-b", 2, '["postgres","python"]', 300.0, 150.0, 1, 1, 1000, 4, '["Alice Dev"]', "2026-01-02"),
                ("creator_a", "alice", "Alice Dev", "alice dev", "ch-a", 3, '["agents"]', 360.0, 120.0, 2, 1, 2000, 8, '["Bob Dev"]', "2026-01-01"),
            ],
        )
    return str(path)


def _sha256(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def test_preview_is_count_only_and_tenant_scoped(tmp_path):
    settings = Settings(sqlite_path=_source_db(tmp_path))
    assert preview_creator_profile_migration(settings).to_dict() == {"creators": 2, "tenants": 2}
    assert preview_creator_profile_migration(settings, user_id="alice").to_dict() == {
        "creators": 1,
        "tenants": 1,
    }


def test_migration_is_read_only_deterministic_idempotent_and_preserves_aggregates(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)
    target = _FakePostgres()
    before = _sha256(path)

    first = migrate_creator_profiles_to_postgres(settings, connection_factory=lambda: target)
    second = migrate_creator_profiles_to_postgres(settings, connection_factory=lambda: target)

    assert _sha256(path) == before
    assert first.to_dict() == {
        "creators_seen": 2,
        "creators_inserted": 2,
        "creators_skipped_existing": 0,
    }
    assert second.to_dict() == {
        "creators_seen": 2,
        "creators_inserted": 0,
        "creators_skipped_existing": 2,
    }
    assert [(row[1], row[3]) for row in target.creator_rows] == [
        ("alice", "alice dev"),
        ("bob", "bob dev"),
    ]
    assert target.creator_rows[0][5:14] == (
        3, '["agents"]', 360.0, 120.0, 2, 1, 2000, 8, '["Bob Dev"]'
    )


def test_tenant_scoped_migration_never_copies_other_tenant(tmp_path):
    settings = Settings(sqlite_path=_source_db(tmp_path))
    target = _FakePostgres()
    report = migrate_creator_profiles_to_postgres(
        settings, user_id="alice", connection_factory=lambda: target
    )
    assert report.creators_seen == 1
    assert [row[1] for row in target.creator_rows] == ["alice"]


def test_invalid_json_is_rejected_before_target_row_mutation(tmp_path):
    path = _source_db(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE creator_profiles SET topics_json = ? WHERE creator_id = ?",
            ('{"not":"a list"}', "creator_a"),
        )
    target = _FakePostgres()
    with pytest.raises(ValueError, match="list of strings"):
        migrate_creator_profiles_to_postgres(
            Settings(sqlite_path=path), connection_factory=lambda: target
        )
    assert target.creator_rows == []


def test_invalid_coverage_counts_fail_before_target_row_mutation(tmp_path):
    path = _source_db(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE creator_profiles SET beginner_count = 4 WHERE creator_id = ?",
            ("creator_a",),
        )
    target = _FakePostgres()
    with pytest.raises(ValueError, match="invalid coverage counts"):
        migrate_creator_profiles_to_postgres(
            Settings(sqlite_path=path), connection_factory=lambda: target
        )
    assert target.creator_rows == []


def test_inconsistent_average_fails_closed(tmp_path):
    path = _source_db(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE creator_profiles SET avg_duration_sec = 999 WHERE creator_id = ?",
            ("creator_b",),
        )
    target = _FakePostgres()
    with pytest.raises(ValueError, match="average duration"):
        migrate_creator_profiles_to_postgres(
            Settings(sqlite_path=path), connection_factory=lambda: target
        )
    assert target.creator_rows == []


def test_normalized_identity_mismatch_fails_closed(tmp_path):
    path = _source_db(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE creator_profiles SET normalized_name = 'wrong' WHERE creator_id = ?",
            ("creator_a",),
        )
    target = _FakePostgres()
    with pytest.raises(ValueError, match="normalized_name"):
        migrate_creator_profiles_to_postgres(
            Settings(sqlite_path=path), connection_factory=lambda: target
        )
    assert target.creator_rows == []


def test_blank_tenant_fails_closed(tmp_path):
    settings = Settings(sqlite_path=_source_db(tmp_path))
    with pytest.raises(ValueError, match="user_id must not be blank"):
        preview_creator_profile_migration(settings, user_id=" ")


def test_missing_source_does_not_create_database(tmp_path):
    path = tmp_path / "missing.db"
    settings = Settings(sqlite_path=str(path))
    with pytest.raises(FileNotFoundError):
        preview_creator_profile_migration(settings)
    assert not path.exists()
