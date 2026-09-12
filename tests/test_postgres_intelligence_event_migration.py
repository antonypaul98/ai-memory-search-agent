from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone

import pytest

from app.config import Settings
from app.db.postgres_intelligence_event_migration import (
    migrate_intelligence_events_to_postgres,
    preview_intelligence_event_migration,
)


class _Cursor:
    def __init__(self, rowcount: int = 0, row=None) -> None:
        self.rowcount = rowcount
        self._row = row

    def fetchone(self):
        return self._row


class _FakePostgres:
    def __init__(self) -> None:
        self.event_ids: set[int] = set()
        self.event_rows: list[tuple] = []
        self.sequence_synced = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=None):
        values = tuple(params) if params is not None else ()
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("select id,user_id,event_type,topic,video_id,query,created_at"):
            event_id = int(values[0])
            row = next((row for row in self.event_rows if int(row[0]) == event_id), None)
            if row is None:
                return _Cursor(0)
            keys = ("id", "user_id", "event_type", "topic", "video_id", "query", "created_at")
            return _Cursor(0, dict(zip(keys, row)))
        if normalized.startswith("insert into intelligence_events"):
            event_id = int(values[0])
            if event_id in self.event_ids:
                return _Cursor(0)
            self.event_ids.add(event_id)
            self.event_rows.append(values)
            return _Cursor(1)
        if "select setval(" in normalized:
            self.sequence_synced = True
            return _Cursor(0)
        return _Cursor(0)


def _source_db(tmp_path) -> str:
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE intelligence_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            topic TEXT,
            video_id TEXT,
            query TEXT,
            created_at TEXT NOT NULL
        );
        """)
        conn.executemany(
            "INSERT INTO intelligence_events VALUES (?,?,?,?,?,?,?)",
            [
                (7, "bob", "search", None, None, "postgres migration", "2026-09-12T08:00:00+00:00"),
                (3, "alice", "save", "agents", "v1", None, "2026-09-11T10:00:00+00:00"),
                (5, "alice", "search", None, None, "agent memory", "2026-09-12T09:00:00+00:00"),
            ],
        )
    return str(path)


def _sha256(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def test_preview_is_count_only_and_tenant_scoped(tmp_path):
    settings = Settings(sqlite_path=_source_db(tmp_path))
    assert preview_intelligence_event_migration(settings).to_dict() == {"events": 3, "tenants": 2}
    assert preview_intelligence_event_migration(settings, user_id="alice").to_dict() == {
        "events": 2,
        "tenants": 1,
    }


def test_migration_is_read_only_deterministic_idempotent_and_resyncs_sequence(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)
    target = _FakePostgres()
    before = _sha256(path)

    first = migrate_intelligence_events_to_postgres(settings, connection_factory=lambda: target)
    second = migrate_intelligence_events_to_postgres(settings, connection_factory=lambda: target)

    assert _sha256(path) == before
    assert first.to_dict() == {
        "events_seen": 3,
        "events_inserted": 3,
        "events_skipped_existing": 0,
    }
    assert second.to_dict() == {
        "events_seen": 3,
        "events_inserted": 0,
        "events_skipped_existing": 3,
    }
    assert [(row[1], row[0]) for row in target.event_rows] == [
        ("alice", 3),
        ("alice", 5),
        ("bob", 7),
    ]
    assert all(isinstance(row[6], datetime) and row[6].tzinfo == timezone.utc for row in target.event_rows)
    assert target.sequence_synced is True


def test_tenant_scoped_migration_never_copies_other_tenant(tmp_path):
    settings = Settings(sqlite_path=_source_db(tmp_path))
    target = _FakePostgres()
    report = migrate_intelligence_events_to_postgres(
        settings, user_id="alice", connection_factory=lambda: target
    )
    assert report.events_seen == 2
    assert [row[1] for row in target.event_rows] == ["alice", "alice"]


def test_nonidentical_target_id_collision_fails_before_new_row_mutation(tmp_path):
    settings = Settings(sqlite_path=_source_db(tmp_path))
    target = _FakePostgres()
    target.event_ids.add(3)
    target.event_rows.append(
        (3, "other-tenant", "search", None, None, "different", datetime(2026, 9, 1, tzinfo=timezone.utc))
    )
    before = list(target.event_rows)

    with pytest.raises(ValueError, match="id collision"):
        migrate_intelligence_events_to_postgres(settings, connection_factory=lambda: target)

    assert target.event_rows == before


def test_blank_identity_fails_before_target_row_mutation(tmp_path):
    path = _source_db(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE intelligence_events SET event_type = '' WHERE id = 3")
    target = _FakePostgres()
    with pytest.raises(ValueError, match="invalid identity"):
        migrate_intelligence_events_to_postgres(
            Settings(sqlite_path=path), connection_factory=lambda: target
        )
    assert target.event_rows == []


def test_invalid_timestamp_fails_before_target_row_mutation(tmp_path):
    path = _source_db(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE intelligence_events SET created_at = 'not-a-date' WHERE id = 3")
    target = _FakePostgres()
    with pytest.raises(ValueError, match="invalid created_at"):
        migrate_intelligence_events_to_postgres(
            Settings(sqlite_path=path), connection_factory=lambda: target
        )
    assert target.event_rows == []


def test_naive_timestamp_fails_closed(tmp_path):
    path = _source_db(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE intelligence_events SET created_at = '2026-09-12T09:00:00' WHERE id = 5")
    target = _FakePostgres()
    with pytest.raises(ValueError, match="must include timezone"):
        migrate_intelligence_events_to_postgres(
            Settings(sqlite_path=path), connection_factory=lambda: target
        )
    assert target.event_rows == []


def test_blank_tenant_filter_fails_closed(tmp_path):
    settings = Settings(sqlite_path=_source_db(tmp_path))
    with pytest.raises(ValueError, match="user_id must not be blank"):
        preview_intelligence_event_migration(settings, user_id=" ")


def test_missing_source_does_not_create_database(tmp_path):
    path = tmp_path / "missing.db"
    settings = Settings(sqlite_path=str(path))
    with pytest.raises(FileNotFoundError):
        preview_intelligence_event_migration(settings)
    assert not path.exists()
