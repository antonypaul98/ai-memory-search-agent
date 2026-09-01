from __future__ import annotations

import hashlib
import sqlite3

import pytest

from app.config import Settings
from app.db.postgres_youtube_memory_migration import (
    migrate_youtube_state_to_postgres,
    preview_youtube_state_migration,
)


class _Cursor:
    def __init__(self, rowcount: int = 0) -> None:
        self.rowcount = rowcount


class _FakePostgres:
    def __init__(self) -> None:
        self.memories: set[tuple[str, str]] = set()
        self.pipeline_keys: set[str] = set()
        self.pipeline_rows: list[tuple] = []
        self.retries: set[tuple[str, str, str]] = set()
        self.metrics: set[tuple[str, str, str]] = set()
        self.statements: list[tuple[str, tuple | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=None):
        values = tuple(params) if params is not None else None
        self.statements.append((sql, values))
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("insert into youtube_memories"):
            key = (values[1], values[2])
            if key in self.memories:
                return _Cursor(0)
            self.memories.add(key)
            return _Cursor(1)
        if normalized.startswith("insert into youtube_sqlite_migration_ledger"):
            key = values[0]
            if key in self.pipeline_keys:
                return _Cursor(0)
            self.pipeline_keys.add(key)
            return _Cursor(1)
        if normalized.startswith("insert into youtube_pipeline_runs"):
            self.pipeline_rows.append(values)
            return _Cursor(1)
        if normalized.startswith("insert into youtube_retry_queue"):
            key = values[:3]
            if key in self.retries:
                return _Cursor(0)
            self.retries.add(key)
            return _Cursor(1)
        if normalized.startswith("insert into youtube_connector_metrics"):
            key = values[:3]
            if key in self.metrics:
                return _Cursor(0)
            self.metrics.add(key)
            return _Cursor(1)
        return _Cursor(0)


def _source_db(tmp_path, *, second_tenant: bool = False, metrics: bool = True) -> str:
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE youtube_memories (
                memory_id TEXT, user_id TEXT, video_id TEXT, url TEXT, title TEXT,
                description TEXT, channel TEXT, channel_id TEXT, published_at TEXT,
                duration_sec REAL, thumbnail TEXT, playback_position_sec REAL, language TEXT,
                transcript_availability TEXT, transcript_kind TEXT, transcript_status TEXT,
                tags_json TEXT, categories_json TEXT, playlist_id TEXT, playlist_title TEXT,
                playlist_index INTEGER, saved_at TEXT, user_notes TEXT, embedding_status TEXT,
                processing_status TEXT, content_hash TEXT, chunk_count INTEGER,
                duplicate_of TEXT, is_duplicate INTEGER, raw_metadata_json TEXT, updated_at TEXT
            );
            CREATE TABLE pipeline_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, user_id TEXT, video_id TEXT,
                capture_id TEXT, stage TEXT, detail TEXT, elapsed_ms REAL, created_at TEXT
            );
            CREATE TABLE connector_retry_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, connector_id TEXT,
                external_id TEXT, url TEXT, payload_json TEXT, attempt_count INTEGER,
                max_attempts INTEGER, next_attempt_at TEXT, last_error TEXT,
                dead_lettered INTEGER, created_at TEXT, updated_at TEXT
            );
            CREATE TABLE connector_metrics (
                metric_key TEXT, connector_id TEXT, value_real REAL,
                value_count INTEGER, updated_at TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO youtube_memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "m1", "alice", "v1", "https://youtu.be/v1", "One", "desc", "chan", "c1",
                None, 10.0, "thumb", None, "en", "available", "manual", "ready", "[]", "[]",
                None, None, None, "2026-01-01T00:00:00+00:00", "note", "ready", "complete",
                "hash1", 2, None, 0, "{}", "2026-01-01T00:00:01+00:00",
            ),
        )
        conn.execute(
            "INSERT INTO pipeline_runs (run_id,user_id,video_id,capture_id,stage,detail,elapsed_ms,created_at) VALUES (?,?,?,?,?,?,?,?)",
            ("run1", "alice", "v1", "cap1", "transcript", "ok", 12.5, "2026-01-01T00:00:02+00:00"),
        )
        conn.execute(
            "INSERT INTO connector_retry_queue (user_id,connector_id,external_id,url,payload_json,attempt_count,max_attempts,next_attempt_at,last_error,dead_lettered,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "alice", "youtube", "v2", "https://youtu.be/v2", "{}", 3, 5,
                "2026-01-02T00:00:00+00:00", "temporary failure", 1,
                "2026-01-01T00:00:00+00:00", "2026-01-01T01:00:00+00:00",
            ),
        )
        if metrics:
            conn.execute(
                "INSERT INTO connector_metrics VALUES (?,?,?,?,?)",
                ("transcript_success", "youtube", 4.0, 4, "2026-01-01T01:00:00+00:00"),
            )
        if second_tenant:
            conn.execute(
                "INSERT INTO youtube_memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "m2", "bob", "v3", "https://youtu.be/v3", "Three", "", "", "", None,
                    None, "", None, None, "unavailable", "none", "pending", "[]", "[]", None,
                    None, None, "2026-01-03T00:00:00+00:00", "", "pending", "queued", "", 0,
                    None, 0, "{}", "2026-01-03T00:00:01+00:00",
                ),
            )
    return str(path)


def _sha256(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def test_preview_is_count_only_and_marks_single_tenant_metrics_safe(tmp_path):
    settings = Settings(sqlite_path=_source_db(tmp_path))

    preview = preview_youtube_state_migration(settings)

    assert preview.to_dict() == {
        "memories": 1,
        "pipeline_stages": 1,
        "retries": 1,
        "legacy_metrics": 1,
        "tenants": 1,
        "metrics_attribution_safe": True,
    }


def test_migration_is_source_read_only_and_target_idempotent(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)
    target = _FakePostgres()
    before = _sha256(path)

    first = migrate_youtube_state_to_postgres(settings, connection_factory=lambda: target)
    second = migrate_youtube_state_to_postgres(settings, connection_factory=lambda: target)

    assert _sha256(path) == before
    assert first.to_dict() == {
        "memories_seen": 1, "memories_inserted": 1, "memories_skipped_existing": 0,
        "pipeline_stages_seen": 1, "pipeline_stages_inserted": 1,
        "pipeline_stages_skipped_existing": 0,
        "retries_seen": 1, "retries_inserted": 1, "retries_skipped_existing": 0,
        "metrics_seen": 1, "metrics_inserted": 1, "metrics_skipped_existing": 0,
    }
    assert second.to_dict() == {
        "memories_seen": 1, "memories_inserted": 0, "memories_skipped_existing": 1,
        "pipeline_stages_seen": 1, "pipeline_stages_inserted": 0,
        "pipeline_stages_skipped_existing": 1,
        "retries_seen": 1, "retries_inserted": 0, "retries_skipped_existing": 1,
        "metrics_seen": 1, "metrics_inserted": 0, "metrics_skipped_existing": 1,
    }
    retry_params = next(
        params for sql, params in target.statements
        if "insert into youtube_retry_queue" in " ".join(sql.split()).lower()
    )
    assert retry_params[8] == "temporary failure"
    assert retry_params[9] is True


def test_ambiguous_global_metrics_fail_before_any_target_write(tmp_path):
    settings = Settings(sqlite_path=_source_db(tmp_path, second_tenant=True))
    preview = preview_youtube_state_migration(settings)
    assert preview.tenants == 2
    assert preview.metrics_attribution_safe is False

    def _must_not_connect():
        raise AssertionError("Postgres must not be contacted for ambiguous metrics")

    with pytest.raises(ValueError, match="cannot be safely attributed"):
        migrate_youtube_state_to_postgres(settings, connection_factory=_must_not_connect)


def test_tenant_filter_is_safe_when_no_legacy_global_metrics_exist(tmp_path):
    settings = Settings(sqlite_path=_source_db(tmp_path, second_tenant=True, metrics=False))
    target = _FakePostgres()

    report = migrate_youtube_state_to_postgres(
        settings, user_id="alice", connection_factory=lambda: target
    )

    assert report.memories_seen == 1
    assert target.memories == {("alice", "v1")}
    assert target.retries == {("alice", "youtube", "v2")}
    assert target.metrics == set()


def test_blank_tenant_and_missing_source_fail_closed(tmp_path):
    path = _source_db(tmp_path)
    settings = Settings(sqlite_path=path)
    with pytest.raises(ValueError, match="must not be blank"):
        preview_youtube_state_migration(settings, user_id="  ")

    missing = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        preview_youtube_state_migration(Settings(sqlite_path=str(missing)))
    assert not missing.exists()
