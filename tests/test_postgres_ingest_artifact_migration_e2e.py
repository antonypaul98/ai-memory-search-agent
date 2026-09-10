"""Real-Postgres artifact migration acceptance, using only the explicit test DSN."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.postgres_ingest_artifact_migration import migrate_ingest_artifacts_to_postgres
from app.db.postgres_ingest_artifact_store import ensure_postgres_ingest_artifact_schema
from app.db.postgres_runtime import get_postgres_connection_factory
from tests.test_postgres_ingest_artifact_migration import _source

TEST_DSN_ENV = "MEMORY_AGENT_TEST_POSTGRES_DSN"
pytestmark = pytest.mark.skipif(not os.getenv(TEST_DSN_ENV), reason="test Postgres DSN not configured")


def test_real_postgres_retry_isolation_and_atomic_rollback(tmp_path):
    import psycopg

    tenant = "artifact-test-" + uuid4().hex
    other = tenant + "-other"
    path = _source(tmp_path, owner=tenant)
    settings = Settings(sqlite_path=str(path), postgres_dsn_env=TEST_DSN_ENV)
    factory = get_postgres_connection_factory(settings)
    ensure_postgres_ingest_artifact_schema(factory)
    try:
        with factory() as conn:
            conn.execute(
                "INSERT INTO ingest_artifacts VALUES (%s, 'video-a', 'newer', NULL, 'target-time')",
                (tenant,),
            )
            conn.execute(
                "INSERT INTO ingest_artifacts VALUES (%s, 'video-a', 'private', 'private-json', 'other-time')",
                (other,),
            )
        # Raise a real SQL error only after hash writes have run. The production
        # transaction context must roll back those writes, not leave half a copy.
        class FailOnCapsule:
            def __init__(self):
                self.conn = factory()
            def __enter__(self):
                self.conn.__enter__()
                return self
            def __exit__(self, *args):
                return self.conn.__exit__(*args)
            def execute(self, sql, params=None):
                if "capsule_json = EXCLUDED.capsule_json" in sql:
                    self.conn.execute("SELECT 1 / 0")
                return self.conn.execute(sql, params)

        with pytest.raises(psycopg.errors.DivisionByZero):
            migrate_ingest_artifacts_to_postgres(settings, user_id=tenant, connection_factory=FailOnCapsule)
        with factory() as conn:
            rows = conn.execute("SELECT * FROM ingest_artifacts WHERE user_id = %s", (tenant,)).fetchall()
            assert len(rows) == 1
            assert rows[0]["transcript_hash"] == "newer"
            assert rows[0]["capsule_json"] is None

        first = migrate_ingest_artifacts_to_postgres(settings, user_id=tenant, connection_factory=factory)
        second = migrate_ingest_artifacts_to_postgres(settings, user_id=tenant, connection_factory=factory)
        assert (first.transcript_hashes_written, first.capsules_written) == (1, 2)
        assert (second.transcript_hashes_written, second.capsules_written) == (0, 0)
        with factory() as conn:
            rows = conn.execute(
                "SELECT * FROM ingest_artifacts WHERE user_id = %s ORDER BY video_id", (tenant,)
            ).fetchall()
            assert [(r["video_id"], r["transcript_hash"], r["capsule_json"], r["updated_at"]) for r in rows] == [
                ("video-a", "newer", '{"a":1}', "target-time"),
                ("video-b", "hash-b", None, "2026-01-02"),
                ("video-c", None, '{"c":1}', "2026-01-04"),
            ]
            other_row = conn.execute("SELECT * FROM ingest_artifacts WHERE user_id = %s", (other,)).fetchone()
            assert (other_row["transcript_hash"], other_row["capsule_json"], other_row["updated_at"]) == (
                "private", "private-json", "other-time"
            )
    finally:
        with factory() as conn:
            conn.execute("DELETE FROM ingest_artifacts WHERE user_id IN (%s, %s)", (tenant, other))
