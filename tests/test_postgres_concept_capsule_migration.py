from __future__ import annotations

import hashlib
import sqlite3

import pytest

from app.config import Settings
from app.db.postgres_concept_capsule_migration import (
    migrate_concept_capsules_to_postgres,
    preview_concept_capsule_migration,
)


class _Cursor:
    def __init__(self, rowcount: int = 0) -> None:
        self.rowcount = rowcount

    def fetchone(self):
        return None


class _FakePostgres:
    def __init__(self) -> None:
        self.capsule_ids: set[str] = set()
        self.capsule_keys: set[tuple[str, str]] = set()
        self.capsule_rows: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=None):
        values = tuple(params) if params is not None else ()
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("insert into concept_capsules"):
            capsule_id, user_id, _name, normalized_name = values[:4]
            key = (user_id, normalized_name)
            if capsule_id in self.capsule_ids or key in self.capsule_keys:
                return _Cursor(0)
            self.capsule_ids.add(capsule_id)
            self.capsule_keys.add(key)
            self.capsule_rows.append(values)
            return _Cursor(1)
        return _Cursor(0)


def _source_db(tmp_path) -> str:
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE concept_capsules (
            capsule_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            topic_ids_json TEXT NOT NULL DEFAULT '[]',
            memory_video_ids_json TEXT NOT NULL DEFAULT '[]',
            creator_names_json TEXT NOT NULL DEFAULT '[]',
            progress_total INTEGER NOT NULL DEFAULT 0,
            progress_completed INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, normalized_name)
        );
        """)
        conn.executemany(
            "INSERT INTO concept_capsules VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("ccap_b", "bob", "Postgres", "postgres", "B", '["tb"]', '["vb1","vb2"]', '["Bob"]', 2, 1, "2026-01-02"),
                ("ccap_a", "alice", "AI Agents", "ai agents", "A", '["ta"]', '["va"]', '["Alice"]', 1, 1, "2026-01-01"),
            ],
        )
    return str(path)


def _sha256(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def test_preview_is_count_only_and_tenant_scoped(tmp_path):
    settings = Settings(sqlite_path=_source_db(tmp_path))
    assert preview_concept_capsule_migration(settings).to_dict() == {"capsules": 2, "tenants": 2}
    assert preview_concept_capsule_migration(settings, user_id="alice").to_dict() == {
        "capsules": 1,
        "tenants": 1,
    }


def test_migration_is_read_only_deterministic_idempotent_and_preserves_aggregate(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)
    target = _FakePostgres()
    before = _sha256(path)

    first = migrate_concept_capsules_to_postgres(settings, connection_factory=lambda: target)
    second = migrate_concept_capsules_to_postgres(settings, connection_factory=lambda: target)

    assert _sha256(path) == before
    assert first.to_dict() == {
        "capsules_seen": 2,
        "capsules_inserted": 2,
        "capsules_skipped_existing": 0,
    }
    assert second.to_dict() == {
        "capsules_seen": 2,
        "capsules_inserted": 0,
        "capsules_skipped_existing": 2,
    }
    assert [(row[1], row[3]) for row in target.capsule_rows] == [
        ("alice", "ai agents"),
        ("bob", "postgres"),
    ]
    assert target.capsule_rows[1][8:10] == (2, 1)


def test_tenant_scoped_migration_never_copies_other_tenant(tmp_path):
    settings = Settings(sqlite_path=_source_db(tmp_path))
    target = _FakePostgres()
    report = migrate_concept_capsules_to_postgres(
        settings, user_id="alice", connection_factory=lambda: target
    )
    assert report.capsules_seen == 1
    assert [row[1] for row in target.capsule_rows] == ["alice"]


def test_invalid_json_is_rejected_before_target_mutation(tmp_path):
    path = _source_db(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE concept_capsules SET topic_ids_json = ? WHERE capsule_id = ?",
            ('{"not":"a list"}', "ccap_a"),
        )
    target = _FakePostgres()
    with pytest.raises(ValueError, match="list of strings"):
        migrate_concept_capsules_to_postgres(
            Settings(sqlite_path=path), connection_factory=lambda: target
        )
    assert target.capsule_rows == []


def test_invalid_progress_is_rejected_before_target_mutation(tmp_path):
    path = _source_db(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE concept_capsules SET progress_completed = 3 WHERE capsule_id = ?",
            ("ccap_b",),
        )
    target = _FakePostgres()
    with pytest.raises(ValueError, match="invalid progress bounds"):
        migrate_concept_capsules_to_postgres(
            Settings(sqlite_path=path), connection_factory=lambda: target
        )
    assert target.capsule_rows == []


def test_normalized_identity_mismatch_fails_closed(tmp_path):
    path = _source_db(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE concept_capsules SET normalized_name = 'wrong' WHERE capsule_id = ?",
            ("ccap_a",),
        )
    target = _FakePostgres()
    with pytest.raises(ValueError, match="normalized_name"):
        migrate_concept_capsules_to_postgres(
            Settings(sqlite_path=path), connection_factory=lambda: target
        )
    assert target.capsule_rows == []


def test_blank_tenant_fails_closed(tmp_path):
    settings = Settings(sqlite_path=_source_db(tmp_path))
    with pytest.raises(ValueError, match="user_id must not be blank"):
        preview_concept_capsule_migration(settings, user_id=" ")


def test_missing_source_does_not_create_database(tmp_path):
    path = tmp_path / "missing.db"
    settings = Settings(sqlite_path=str(path))
    with pytest.raises(FileNotFoundError):
        preview_concept_capsule_migration(settings)
    assert not path.exists()
