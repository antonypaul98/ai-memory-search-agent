from __future__ import annotations

import sqlite3

import pytest

from app.config import Settings
from app.db.postgres_content_url_index_migration import (
    migrate_content_url_index_to_postgres,
    preview_content_url_index_migration,
)


class _Cursor:
    def __init__(self, *, rowcount=0, rows=None):
        self.rowcount = rowcount
        self._rows = rows or []

    def fetchall(self):
        return self._rows


class _Connection:
    def __init__(self, state, *, hide_hash=None):
        self.state = state
        self.hide_hash = hide_hash
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())
        packed = tuple(params) if params is not None else None
        self.calls.append((normalized, packed))
        if normalized.startswith("INSERT INTO content_url_index"):
            key = (packed[0], packed[1])
            if key in self.state:
                return _Cursor(rowcount=0)
            self.state[key] = {
                "canonical_url": packed[2],
                "content_hash": packed[3],
                "source_type": packed[4],
                "connector_id": packed[5],
                "external_id": packed[6],
                "memory_id": packed[7],
                "created_at": packed[8],
            }
            return _Cursor(rowcount=1)
        if normalized.startswith("SELECT url_hash FROM content_url_index"):
            tenant = packed[0]
            rows = [
                {"url_hash": url_hash}
                for (user_id, url_hash) in sorted(self.state)
                if user_id == tenant and url_hash != self.hide_hash
            ]
            return _Cursor(rows=rows)
        return _Cursor()


class _Factory:
    def __init__(self, state=None, *, hide_hash=None):
        self.state = state if state is not None else {}
        self.hide_hash = hide_hash
        self.connections = []

    def __call__(self):
        conn = _Connection(self.state, hide_hash=self.hide_hash)
        self.connections.append(conn)
        return conn

    @property
    def calls(self):
        return [call for conn in self.connections for call in conn.calls]


def _source(tmp_path):
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE content_url_index (
                user_id TEXT NOT NULL,
                url_hash TEXT NOT NULL,
                canonical_url TEXT NOT NULL,
                content_hash TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL,
                connector_id TEXT NOT NULL,
                external_id TEXT NOT NULL,
                memory_id TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, url_hash)
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO content_url_index (
                user_id, url_hash, canonical_url, content_hash, source_type,
                connector_id, external_id, memory_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("tenant-a", "hash-b", "https://b.example", "content-1", "web", "web.v1", "b", "m-b", "2026-01-02"),
                ("tenant-b", "hash-x", "https://x.example", "content-x", "web", "web.v1", "x", "m-x", "2026-01-01"),
                ("tenant-a", "hash-a", "https://a.example", "content-1", "pdf", "pdf.v1", "a", "m-a", "2026-01-01"),
            ],
        )
    return path


def test_preview_is_count_only_and_exact_tenant_scoped(tmp_path):
    path = _source(tmp_path)
    preview = preview_content_url_index_migration(
        Settings(sqlite_path=str(path)), user_id="tenant-a"
    )
    assert preview.to_dict() == {"rows": 2, "tenant": "tenant-a"}


@pytest.mark.parametrize("tenant", ["", "  ", " tenant-a", "tenant-a "])
def test_invalid_tenant_identity_fails_closed(tmp_path, tenant):
    path = _source(tmp_path)
    with pytest.raises(ValueError, match="exact tenant identity"):
        preview_content_url_index_migration(Settings(sqlite_path=str(path)), user_id=tenant)


def test_migration_is_tenant_scoped_deterministic_idempotent_and_target_authoritative(tmp_path):
    path = _source(tmp_path)
    existing = {
        ("tenant-a", "hash-a"): {
            "canonical_url": "https://newer.example",
            "content_hash": "newer-content",
            "source_type": "web",
            "connector_id": "web.v2",
            "external_id": "newer",
            "memory_id": "newer-memory",
            "created_at": "2026-02-01",
        }
    }
    factory = _Factory(existing)
    settings = Settings(sqlite_path=str(path))

    first = migrate_content_url_index_to_postgres(
        settings, user_id="tenant-a", connection_factory=factory
    )
    second = migrate_content_url_index_to_postgres(
        settings, user_id="tenant-a", connection_factory=factory
    )

    assert first.to_dict() == {
        "rows_seen": 2,
        "rows_written": 1,
        "rows_skipped_existing": 1,
        "tenant": "tenant-a",
    }
    assert second.rows_written == 0
    assert existing[("tenant-a", "hash-a")]["canonical_url"] == "https://newer.example"
    assert ("tenant-b", "hash-x") not in factory.state
    inserts = [params for sql, params in factory.calls if sql.startswith("INSERT INTO content_url_index")]
    assert [params[1] for params in inserts[:2]] == ["hash-a", "hash-b"]
    assert all(params[0] == "tenant-a" for params in inserts)


def test_parity_failure_raises_inside_target_transaction(tmp_path):
    path = _source(tmp_path)
    factory = _Factory(hide_hash="hash-b")

    with pytest.raises(RuntimeError, match="target missing 1 source identities"):
        migrate_content_url_index_to_postgres(
            Settings(sqlite_path=str(path)), user_id="tenant-a", connection_factory=factory
        )


def test_source_is_opened_read_only(tmp_path):
    path = _source(tmp_path)
    before = path.read_bytes()
    migrate_content_url_index_to_postgres(
        Settings(sqlite_path=str(path)), user_id="tenant-a", connection_factory=_Factory()
    )
    assert path.read_bytes() == before


def test_missing_source_fails_without_creating_database(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError, match="migration source does not exist"):
        preview_content_url_index_migration(Settings(sqlite_path=str(path)), user_id="tenant-a")
    assert not path.exists()


def test_missing_source_table_fails_before_postgres(tmp_path):
    path = tmp_path / "empty.db"
    with sqlite3.connect(path):
        pass
    factory = _Factory()
    with pytest.raises(ValueError, match="source table is missing"):
        migrate_content_url_index_to_postgres(
            Settings(sqlite_path=str(path)), user_id="tenant-a", connection_factory=factory
        )
    assert factory.connections == []
