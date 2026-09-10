from __future__ import annotations

import sqlite3

import pytest

from app.config import Settings
from app.db.postgres_ingest_artifact_migration import (
    migrate_ingest_artifacts_to_postgres,
    preview_ingest_artifact_migration,
)


class _Cursor:
    def __init__(self, rowcount=0):
        self.rowcount = rowcount


class _Connection:
    def __init__(self, state):
        self.state = state
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())
        packed = tuple(params) if params is not None else None
        self.calls.append((normalized, packed))
        if normalized.startswith("INSERT INTO ingest_artifacts"):
            user_id, video_id = packed[0], packed[1]
            key = (user_id, video_id)
            row = self.state.setdefault(key, {"transcript_hash": None, "capsule_json": None})
            if "transcript_hash = EXCLUDED.transcript_hash" in normalized:
                if row["transcript_hash"] is not None:
                    return _Cursor(0)
                row["transcript_hash"] = packed[2]
                return _Cursor(1)
            if "capsule_json = EXCLUDED.capsule_json" in normalized:
                if row["capsule_json"] is not None:
                    return _Cursor(0)
                row["capsule_json"] = packed[2]
                return _Cursor(1)
        return _Cursor(0)


class _Factory:
    def __init__(self, state=None):
        self.state = state if state is not None else {}
        self.connections = []

    def __call__(self):
        conn = _Connection(self.state)
        self.connections.append(conn)
        return conn

    @property
    def calls(self):
        return [call for conn in self.connections for call in conn.calls]


def _source(tmp_path, *, owner="tenant-a", second_owner=None):
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE content_hashes (
                video_id TEXT PRIMARY KEY,
                transcript_hash TEXT NOT NULL,
                normalized_path TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE memory_capsules_json (
                video_id TEXT PRIMARY KEY,
                capsule_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE youtube_memories (
                memory_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                video_id TEXT NOT NULL
            );
            CREATE TABLE memory_records (
                memory_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                external_id TEXT NOT NULL
            );
            """
        )
        conn.executemany(
            "INSERT INTO content_hashes(video_id, transcript_hash, normalized_path, updated_at) VALUES (?, ?, '', ?)",
            [("video-b", "hash-b", "2026-01-02"), ("video-a", "hash-a", "2026-01-01")],
        )
        conn.executemany(
            "INSERT INTO memory_capsules_json(video_id, capsule_json, updated_at) VALUES (?, ?, ?)",
            [("video-a", '{"a":1}', "2026-01-03"), ("video-c", '{"c":1}', "2026-01-04")],
        )
        conn.executemany(
            "INSERT INTO youtube_memories(memory_id, user_id, video_id) VALUES (?, ?, ?)",
            [("m-a", owner, "video-a"), ("m-b", owner, "video-b")],
        )
        conn.execute(
            "INSERT INTO memory_records(memory_id, user_id, source_type, external_id) VALUES (?, ?, ?, ?)",
            ("r-c", owner, "youtube", "video-c"),
        )
        if second_owner:
            conn.execute(
                "INSERT INTO youtube_memories(memory_id, user_id, video_id) VALUES (?, ?, ?)",
                ("m-a-2", second_owner, "video-a"),
            )
    return path


def test_preview_is_count_only_and_validates_tenant_evidence(tmp_path):
    path = _source(tmp_path)
    preview = preview_ingest_artifact_migration(
        Settings(sqlite_path=str(path)), user_id="tenant-a"
    )
    assert preview.to_dict() == {
        "transcript_hashes": 2,
        "capsules": 2,
        "distinct_videos": 3,
        "tenant": "tenant-a",
    }


def test_blank_tenant_fails_closed(tmp_path):
    path = _source(tmp_path)
    with pytest.raises(ValueError, match="have no tenant identity"):
        preview_ingest_artifact_migration(Settings(sqlite_path=str(path)), user_id="  ")


def test_contradictory_tenant_evidence_fails_before_postgres(tmp_path):
    path = _source(tmp_path, owner="tenant-b")
    factory = _Factory()
    with pytest.raises(ValueError, match="contradicts tenant-bearing"):
        migrate_ingest_artifacts_to_postgres(
            Settings(sqlite_path=str(path)), user_id="tenant-a", connection_factory=factory
        )
    assert factory.connections == []


def test_multi_tenant_video_evidence_is_ambiguous_even_with_selection(tmp_path):
    path = _source(tmp_path, second_owner="tenant-b")
    with pytest.raises(ValueError, match="ambiguous across multiple tenants"):
        preview_ingest_artifact_migration(Settings(sqlite_path=str(path)), user_id="tenant-a")


def test_migration_is_deterministic_idempotent_and_field_preserving(tmp_path):
    path = _source(tmp_path)
    settings = Settings(sqlite_path=str(path))
    factory = _Factory(
        {("tenant-a", "video-a"): {"transcript_hash": "newer-hash", "capsule_json": None}}
    )

    first = migrate_ingest_artifacts_to_postgres(
        settings, user_id="tenant-a", connection_factory=factory
    )
    second = migrate_ingest_artifacts_to_postgres(
        settings, user_id="tenant-a", connection_factory=factory
    )

    assert first.transcript_hashes_seen == 2
    assert first.transcript_hashes_written == 1
    assert first.transcript_hashes_skipped_existing == 1
    assert first.capsules_seen == 2
    assert first.capsules_written == 2
    assert second.transcript_hashes_written == 0
    assert second.capsules_written == 0
    assert factory.state[("tenant-a", "video-a")]["transcript_hash"] == "newer-hash"
    assert factory.state[("tenant-a", "video-a")]["capsule_json"] == '{"a":1}'
    inserts = [params for sql, params in factory.calls if sql.startswith("INSERT INTO ingest_artifacts")]
    assert [params[1] for params in inserts[:2]] == ["video-a", "video-b"]
    assert all(params[0] == "tenant-a" for params in inserts)


def test_source_is_opened_read_only(tmp_path):
    path = _source(tmp_path)
    before = path.read_bytes()
    migrate_ingest_artifacts_to_postgres(
        Settings(sqlite_path=str(path)), user_id="tenant-a", connection_factory=_Factory()
    )
    assert path.read_bytes() == before


def test_missing_source_fails_without_creating_database(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError, match="migration source does not exist"):
        preview_ingest_artifact_migration(Settings(sqlite_path=str(path)), user_id="tenant-a")
    assert not path.exists()


@pytest.mark.parametrize("operation", ["preview", "apply"])
@pytest.mark.parametrize("missing", ["tables", "hash", "capsule", "wrong-source"])
def test_unproven_ownership_fails_closed(tmp_path, operation, missing):
    path = _source(tmp_path)
    with sqlite3.connect(path) as conn:
        if missing == "tables":
            conn.executescript("DROP TABLE youtube_memories; DROP TABLE memory_records;")
        elif missing == "hash":
            conn.execute("DELETE FROM youtube_memories WHERE video_id = 'video-b'")
        elif missing == "capsule":
            conn.execute("DELETE FROM memory_records")
        else:
            conn.execute("UPDATE memory_records SET source_type = 'web'")
    factory = _Factory()
    with pytest.raises(ValueError, match="no tenant-bearing proof"):
        if operation == "preview":
            preview_ingest_artifact_migration(Settings(sqlite_path=str(path)), user_id="tenant-a")
        else:
            migrate_ingest_artifacts_to_postgres(
                Settings(sqlite_path=str(path)), user_id="tenant-a", connection_factory=factory
            )
    assert factory.connections == []


@pytest.mark.parametrize("owner", [None, "", "  ", " tenant-a "])
def test_invalid_evidence_cannot_be_ignored_or_normalized(tmp_path, owner):
    path = _source(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("ALTER TABLE youtube_memories RENAME TO old_memories")
        conn.execute("CREATE TABLE youtube_memories (user_id, video_id TEXT)")
        conn.execute("INSERT INTO youtube_memories SELECT user_id, video_id FROM old_memories")
        conn.execute("INSERT INTO youtube_memories VALUES (?, 'video-a')", (owner,))
    factory = _Factory()
    with pytest.raises(ValueError, match="ownership evidence is invalid"):
        migrate_ingest_artifacts_to_postgres(
            Settings(sqlite_path=str(path)), user_id="tenant-a", connection_factory=factory
        )
    assert factory.connections == []


@pytest.mark.parametrize("source_type", ["youtube", "youtube.v1"])
def test_canonical_only_proof_and_conflicting_cross_table_proof(tmp_path, source_type):
    path = _source(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO memory_records SELECT memory_id, user_id, ?, video_id FROM youtube_memories",
            (source_type,),
        )
        conn.execute("DELETE FROM youtube_memories")
    assert preview_ingest_artifact_migration(
        Settings(sqlite_path=str(path)), user_id="tenant-a"
    ).distinct_videos == 3
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO youtube_memories VALUES ('conflict', 'tenant-b', 'video-a')")
    factory = _Factory()
    with pytest.raises(ValueError, match="ambiguous across multiple tenants"):
        migrate_ingest_artifacts_to_postgres(
            Settings(sqlite_path=str(path)), user_id="tenant-a", connection_factory=factory
        )
    assert factory.connections == []


def test_artifacts_and_ownership_share_snapshot_and_connection_closes(tmp_path, monkeypatch):
    import app.db.postgres_ingest_artifact_migration as migration

    path = _source(tmp_path, owner="tenant-b")
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
    original_read = migration._read_source_rows
    opened = []

    def concurrent_change(source):
        rows = original_read(source)
        opened.append(source)
        # A writer commits after artifact reads but before ownership validation.
        with sqlite3.connect(path) as writer:
            writer.execute("UPDATE youtube_memories SET user_id = 'tenant-a'")
            writer.execute("UPDATE memory_records SET user_id = 'tenant-a'")
        return rows

    monkeypatch.setattr(migration, "_read_source_rows", concurrent_change)
    factory = _Factory()
    with pytest.raises(ValueError, match="contradicts tenant-bearing"):
        migrate_ingest_artifacts_to_postgres(
            Settings(sqlite_path=str(path)), user_id="tenant-a", connection_factory=factory
        )
    assert factory.connections == []
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")
    monkeypatch.setattr(migration, "_read_source_rows", original_read)
    assert preview_ingest_artifact_migration(
        Settings(sqlite_path=str(path)), user_id="tenant-a"
    ).distinct_videos == 3


def test_cli_defaults_to_preview_and_apply_revalidates(tmp_path, monkeypatch, capsys):
    import json
    import sys
    from scripts import migrate_ingest_artifacts_to_postgres as cli

    path = _source(tmp_path)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(sqlite_path=str(path)))
    monkeypatch.setattr(sys, "argv", ["migration", "--user-id", "tenant-a"])
    def unexpected_apply(*args, **kwargs):
        pytest.fail("preview must not apply")
    monkeypatch.setattr(cli, "migrate_ingest_artifacts_to_postgres", unexpected_apply)
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out) == {
        "mode": "preview", "tenant": "tenant-a", "transcript_hashes": 2,
        "capsules": 2, "distinct_videos": 3,
    }
    factory = _Factory()
    def apply_after_change(settings, *, user_id):
        with sqlite3.connect(path) as writer:
            writer.execute("DELETE FROM memory_records")
        return migrate_ingest_artifacts_to_postgres(
            settings, user_id=user_id, connection_factory=factory
        )
    monkeypatch.setattr(cli, "migrate_ingest_artifacts_to_postgres", apply_after_change)
    monkeypatch.setattr(sys, "argv", ["migration", "--user-id", "tenant-a", "--apply"])
    with pytest.raises(ValueError, match="no tenant-bearing proof"):
        cli.main()
    assert factory.connections == []
