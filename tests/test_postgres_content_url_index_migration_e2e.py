"""Real-Postgres acceptance for tenant-scoped content URL index migration."""
from __future__ import annotations

import os
import sqlite3
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.postgres_content_url_index_migration import migrate_content_url_index_to_postgres
from app.db.postgres_content_url_index_store import ensure_postgres_content_url_index_schema
from app.db.postgres_runtime import get_postgres_connection_factory

TEST_DSN_ENV = "MEMORY_AGENT_TEST_POSTGRES_DSN"
pytestmark = pytest.mark.skipif(not os.getenv(TEST_DSN_ENV), reason="test Postgres DSN not configured")


def _source(tmp_path, *, tenant: str):
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
                (tenant, "hash-a", "https://a.example", "content-a", "web", "web.v1", "a", "memory-a", "2026-01-01"),
                (tenant, "hash-b", "https://b.example", "content-b", "pdf", "pdf.v1", "b", "memory-b", "2026-01-02"),
            ],
        )
    return path


def test_real_postgres_retry_isolation_target_preservation_and_atomic_rollback(tmp_path):
    import psycopg

    tenant = "content-url-test-" + uuid4().hex
    other = tenant + "-other"
    path = _source(tmp_path, tenant=tenant)
    settings = Settings(sqlite_path=str(path), postgres_dsn_env=TEST_DSN_ENV)
    factory = get_postgres_connection_factory(settings)
    ensure_postgres_content_url_index_schema(factory)

    class FailAfterFirstInsert:
        def __init__(self):
            self.conn = factory()
            self.inserts = 0

        def __enter__(self):
            self.conn.__enter__()
            return self

        def __exit__(self, *args):
            return self.conn.__exit__(*args)

        def execute(self, sql, params=None):
            normalized = " ".join(str(sql).split())
            if normalized.startswith("INSERT INTO content_url_index"):
                self.inserts += 1
                if self.inserts == 2:
                    self.conn.execute("SELECT 1 / 0")
            return self.conn.execute(sql, params)

    try:
        with pytest.raises(psycopg.errors.DivisionByZero):
            migrate_content_url_index_to_postgres(
                settings,
                user_id=tenant,
                connection_factory=FailAfterFirstInsert,
            )

        with factory() as conn:
            assert conn.execute(
                "SELECT COUNT(*) AS n FROM content_url_index WHERE user_id = %s",
                (tenant,),
            ).fetchone()["n"] == 0

            conn.execute(
                """
                INSERT INTO content_url_index (
                    user_id, url_hash, canonical_url, content_hash, source_type,
                    connector_id, external_id, memory_id, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    tenant,
                    "hash-a",
                    "https://newer.example",
                    "newer-content",
                    "web",
                    "web.v2",
                    "newer",
                    "newer-memory",
                    "2026-02-01",
                ),
            )
            conn.execute(
                """
                INSERT INTO content_url_index (
                    user_id, url_hash, canonical_url, content_hash, source_type,
                    connector_id, external_id, memory_id, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    other,
                    "hash-b",
                    "https://private.example",
                    "private-content",
                    "web",
                    "web.v1",
                    "private",
                    "private-memory",
                    "2026-01-03",
                ),
            )

        first = migrate_content_url_index_to_postgres(
            settings,
            user_id=tenant,
            connection_factory=factory,
        )
        second = migrate_content_url_index_to_postgres(
            settings,
            user_id=tenant,
            connection_factory=factory,
        )

        assert first.rows_seen == 2
        assert first.rows_written == 1
        assert first.rows_skipped_existing == 1
        assert second.rows_written == 0
        assert second.rows_skipped_existing == 2

        with factory() as conn:
            rows = conn.execute(
                """
                SELECT user_id, url_hash, canonical_url, content_hash, source_type,
                       connector_id, external_id, memory_id, created_at::text AS created_at
                FROM content_url_index
                WHERE user_id = %s
                ORDER BY url_hash
                """,
                (tenant,),
            ).fetchall()
            assert [(row["url_hash"], row["canonical_url"], row["content_hash"]) for row in rows] == [
                ("hash-a", "https://newer.example", "newer-content"),
                ("hash-b", "https://b.example", "content-b"),
            ]
            other_row = conn.execute(
                "SELECT canonical_url, content_hash FROM content_url_index WHERE user_id = %s AND url_hash = %s",
                (other, "hash-b"),
            ).fetchone()
            assert (other_row["canonical_url"], other_row["content_hash"]) == (
                "https://private.example",
                "private-content",
            )
    finally:
        with factory() as conn:
            conn.execute("DELETE FROM content_url_index WHERE user_id IN (%s, %s)", (tenant, other))
