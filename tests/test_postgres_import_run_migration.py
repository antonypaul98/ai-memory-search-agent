from __future__ import annotations

import hashlib
import sqlite3

import pytest

from app.config import Settings
from app.db.postgres_import_run_migration import (
    migrate_import_runs_to_postgres,
    preview_import_run_migration,
)


class _Cursor:
    def __init__(self, rowcount: int = 0) -> None:
        self.rowcount = rowcount


class _FakePostgres:
    def __init__(self) -> None:
        self.run_ids: set[str] = set()
        self.inserted_runs: list[tuple] = []
        self.inserted_items: list[tuple] = []
        self.statements: list[tuple[str, tuple | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=None):
        values = tuple(params) if params is not None else None
        self.statements.append((sql, values))
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("insert into import_runs"):
            import_id = values[0]
            if import_id in self.run_ids:
                return _Cursor(0)
            self.run_ids.add(import_id)
            self.inserted_runs.append(values)
            return _Cursor(1)
        if normalized.startswith("insert into import_run_items"):
            self.inserted_items.append(values)
            return _Cursor(1)
        return _Cursor(0)


def _source_db(tmp_path) -> str:
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE import_runs (
                import_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                connector_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                total_items INTEGER NOT NULL DEFAULT 0,
                completed_items INTEGER NOT NULL DEFAULT 0,
                failed_items INTEGER NOT NULL DEFAULT 0,
                skipped_items INTEGER NOT NULL DEFAULT 0,
                duplicate_items INTEGER NOT NULL DEFAULT 0,
                unsupported_items INTEGER NOT NULL DEFAULT 0,
                detail TEXT NOT NULL DEFAULT '',
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE import_run_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                import_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                url TEXT NOT NULL,
                external_id TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'queued',
                detail TEXT NOT NULL DEFAULT '',
                error TEXT,
                capture_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.executemany(
            "INSERT INTO import_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "run-b", "bob", "readwise.v1", "completed", 1, 1, 0, 0, 0, 0,
                    "Done", None, "2026-01-02T00:00:00+00:00", "2026-01-02T00:02:00+00:00",
                ),
                (
                    "run-a", "alice", "notion.v1", "processing", 2, 1, 1, 0, 0, 0,
                    "Halfway", "one item failed", "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:03:00+00:00",
                ),
            ],
        )
        conn.executemany(
            """
            INSERT INTO import_run_items (
                import_id, user_id, url, external_id, title, status, detail, error,
                capture_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "run-a", "alice", "https://example.com/a2", "ext-a2", "A2", "failed",
                    "Fetch failed", "private source unavailable", None,
                    "2026-01-01T00:00:02+00:00", "2026-01-01T00:03:00+00:00",
                ),
                (
                    "run-b", "bob", "https://example.com/b1", "ext-b1", "B1", "completed",
                    "Saved", None, "capture-b1", "2026-01-02T00:00:01+00:00",
                    "2026-01-02T00:02:00+00:00",
                ),
                (
                    "run-a", "alice", "https://example.com/a1", "ext-a1", "A1", "completed",
                    "Saved", None, "capture-a1", "2026-01-01T00:00:01+00:00",
                    "2026-01-01T00:01:00+00:00",
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

    all_rows = preview_import_run_migration(settings)
    alice = preview_import_run_migration(settings, user_id="alice")

    assert all_rows.to_dict() == {"runs": 2, "items": 3, "tenants": 2}
    assert alice.to_dict() == {"runs": 1, "items": 2, "tenants": 1}


def test_migration_is_read_only_deterministic_and_idempotent(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)
    target = _FakePostgres()
    before = _sha256(path)

    first = migrate_import_runs_to_postgres(settings, connection_factory=lambda: target)
    second = migrate_import_runs_to_postgres(settings, connection_factory=lambda: target)

    assert _sha256(path) == before
    assert first.to_dict() == {
        "runs_seen": 2,
        "runs_inserted": 2,
        "runs_skipped_existing": 0,
        "items_seen": 3,
        "items_inserted": 3,
        "items_skipped_existing_run": 0,
    }
    assert second.to_dict() == {
        "runs_seen": 2,
        "runs_inserted": 0,
        "runs_skipped_existing": 2,
        "items_seen": 3,
        "items_inserted": 0,
        "items_skipped_existing_run": 3,
    }
    assert [(row[1], row[0]) for row in target.inserted_runs] == [
        ("alice", "run-a"),
        ("bob", "run-b"),
    ]
    assert [(row[1], row[0], row[2]) for row in target.inserted_items] == [
        ("alice", "run-a", "https://example.com/a2"),
        ("alice", "run-a", "https://example.com/a1"),
        ("bob", "run-b", "https://example.com/b1"),
    ]


def test_existing_target_run_is_authoritative_and_skips_its_items(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)
    target = _FakePostgres()
    target.run_ids.add("run-a")

    report = migrate_import_runs_to_postgres(settings, connection_factory=lambda: target)

    assert report.to_dict() == {
        "runs_seen": 2,
        "runs_inserted": 1,
        "runs_skipped_existing": 1,
        "items_seen": 3,
        "items_inserted": 1,
        "items_skipped_existing_run": 2,
    }
    assert [row[0] for row in target.inserted_items] == ["run-b"]


def test_exact_tenant_preserves_full_run_and_item_business_state(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)
    target = _FakePostgres()

    report = migrate_import_runs_to_postgres(
        settings,
        user_id="alice",
        connection_factory=lambda: target,
    )

    assert report.runs_seen == 1
    assert report.items_seen == 2
    run = target.inserted_runs[0]
    assert run[0:4] == ("run-a", "alice", "notion.v1", "processing")
    assert run[4:12] == (2, 1, 1, 0, 0, 0, "Halfway", "one item failed")
    failed_item = target.inserted_items[0]
    assert failed_item[0:2] == ("run-a", "alice")
    assert failed_item[3:9] == (
        "ext-a2", "A2", "failed", "Fetch failed", "private source unavailable", None,
    )
    # SQLite surrogate IDs are intentionally absent from the Postgres insert.
    assert len(failed_item) == 11


def test_blank_tenant_fails_closed(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)

    with pytest.raises(ValueError, match="user_id must not be blank"):
        preview_import_run_migration(settings, user_id="   ")


def test_missing_sqlite_source_fails_without_creating_a_database(tmp_path):
    path = tmp_path / "missing.db"
    settings = Settings(sqlite_path=str(path))

    with pytest.raises(FileNotFoundError):
        preview_import_run_migration(settings)

    assert not path.exists()
