from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from app.db import postgres_semantic_cache_migration as migration


class _Result:
    def __init__(self, rowcount: int = 0) -> None:
        self.rowcount = rowcount


class _TargetConnection:
    def __init__(self, existing: set[tuple[str, str]]) -> None:
        self.existing = existing
        self.inserts: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=()):
        if "INSERT INTO semantic_cache" in sql:
            key = (str(params[0]), str(params[1]))
            if key in self.existing:
                return _Result(0)
            self.existing.add(key)
            self.inserts.append(tuple(params))
            return _Result(1)
        return _Result(0)


class _TargetStore:
    def __init__(self, _factory) -> None:
        pass

    def versions(self) -> tuple[str, str]:
        return "7", "3"


def _source(tmp_path):
    path = tmp_path / "memory.db"
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE semantic_cache (
            user_id TEXT NOT NULL,
            cache_key TEXT NOT NULL,
            question_normalized TEXT NOT NULL,
            question_embedding TEXT,
            answer_json TEXT NOT NULL,
            query_type TEXT NOT NULL,
            memory_index_version TEXT NOT NULL,
            preference_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
        """
    )
    rows = [
        ("tenant-a", "a:one", "one", "[1.0]", "{\"a\":1}", "lookup", "7", "3", "2026-01-01T00:00:00+00:00", "2030-01-01T00:00:00+00:00"),
        ("tenant-a", "a:old", "old", "[0.5]", "{\"a\":2}", "lookup", "6", "3", "2026-01-01T00:00:00+00:00", "2030-01-01T00:00:00+00:00"),
        ("tenant-b", "b:one", "one", None, "{\"b\":1}", "lookup", "7", "3", "2026-01-01T00:00:00+00:00", "2030-01-01T00:00:00+00:00"),
    ]
    conn.executemany("INSERT INTO semantic_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()
    return path


def test_preview_is_count_only_and_does_not_contact_postgres(tmp_path, monkeypatch):
    path = _source(tmp_path)
    settings = SimpleNamespace(sqlite_path=str(path))
    monkeypatch.setattr(
        migration,
        "get_postgres_connection_factory",
        lambda _settings: (_ for _ in ()).throw(AssertionError("preview contacted Postgres")),
    )

    report = migration.preview_semantic_cache_migration(settings)

    assert report.to_dict() == {"rows": 3, "tenants": 2}


def test_migration_preserves_tenants_versions_and_existing_target_rows(tmp_path, monkeypatch):
    path = _source(tmp_path)
    settings = SimpleNamespace(sqlite_path=str(path))
    existing = {("tenant-b", "b:one")}
    target = _TargetConnection(existing)
    monkeypatch.setattr(migration, "PostgresSemanticCacheStore", _TargetStore)

    report = migration.migrate_semantic_cache_to_postgres(
        settings,
        connection_factory=lambda: target,
    )

    assert report.to_dict() == {
        "rows_seen": 3,
        "rows_compatible": 2,
        "rows_inserted": 1,
        "rows_skipped_incompatible": 1,
        "rows_skipped_existing": 1,
    }
    assert [(row[0], row[1]) for row in target.inserts] == [("tenant-a", "a:one")]
    assert target.inserts[0][3] == b"[1.0]"


def test_tenant_scoped_migration_never_reads_another_tenant(tmp_path, monkeypatch):
    path = _source(tmp_path)
    settings = SimpleNamespace(sqlite_path=str(path))
    target = _TargetConnection(set())
    monkeypatch.setattr(migration, "PostgresSemanticCacheStore", _TargetStore)

    report = migration.migrate_semantic_cache_to_postgres(
        settings,
        user_id="tenant-b",
        connection_factory=lambda: target,
    )

    assert report.rows_seen == 1
    assert [(row[0], row[1]) for row in target.inserts] == [("tenant-b", "b:one")]


def test_blank_explicit_tenant_fails_closed(tmp_path):
    path = _source(tmp_path)
    settings = SimpleNamespace(sqlite_path=str(path))

    with pytest.raises(ValueError, match="non-empty"):
        migration.preview_semantic_cache_migration(settings, user_id="   ")


def test_missing_source_fails_closed(tmp_path):
    settings = SimpleNamespace(sqlite_path=str(tmp_path / "missing.db"))

    with pytest.raises(FileNotFoundError):
        migration.preview_semantic_cache_migration(settings)
