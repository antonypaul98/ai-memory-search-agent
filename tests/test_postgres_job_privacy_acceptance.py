"""Real-Postgres acceptance for tenant job erasure and stale worker fencing."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.db.postgres_job_claims import PostgresJobClaimStore
from app.db.postgres_job_privacy import PostgresJobPrivacyStore


def test_job_erasure_is_tenant_exact_and_rejects_late_worker():
    if not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"):
        pytest.skip("real Postgres DSN required")

    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    base_dsn = os.environ["MEMORY_AGENT_TEST_POSTGRES_DSN"]
    schema = "p03_job_privacy_" + uuid4().hex
    with psycopg.connect(base_dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    scoped_dsn = make_conninfo(base_dsn, options=f"-c search_path={schema}")

    def factory():
        return psycopg.connect(scoped_dsn)

    now = datetime.now(timezone.utc)
    owner, neighbor = "owner-" + uuid4().hex, "neighbor-" + uuid4().hex
    owner_job, neighbor_job = "job-" + uuid4().hex, "job-" + uuid4().hex
    owner_item, neighbor_item = "item-owner", "item-neighbor"
    stale_worker = "worker-stale"

    try:
        with factory() as conn:
            conn.execute("""CREATE TABLE background_jobs (
                job_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, status TEXT NOT NULL,
                paused BOOLEAN NOT NULL DEFAULT FALSE, processing INTEGER NOT NULL DEFAULT 0,
                completed INTEGER NOT NULL DEFAULT 0, skipped INTEGER NOT NULL DEFAULT 0,
                failed INTEGER NOT NULL DEFAULT 0, lease_owner TEXT, lease_until TIMESTAMPTZ,
                finished_at TIMESTAMPTZ)""")
            conn.execute("""CREATE TABLE job_items (
                id BIGSERIAL PRIMARY KEY, job_id TEXT NOT NULL, user_id TEXT NOT NULL,
                item_key TEXT NOT NULL, url TEXT NOT NULL, status TEXT NOT NULL,
                error TEXT, updated_at TIMESTAMPTZ NOT NULL,
                UNIQUE(job_id, item_key))""")
            conn.execute("""CREATE TABLE job_events (
                id BIGSERIAL PRIMARY KEY, job_id TEXT NOT NULL, event_type TEXT NOT NULL,
                message TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL)""")
            conn.execute("""CREATE TABLE job_item_leases (
                job_id TEXT NOT NULL, item_key TEXT NOT NULL, worker_id TEXT NOT NULL,
                lease_until TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY(job_id, item_key))""")
            for job_id, user_id, item_key in (
                (owner_job, owner, owner_item), (neighbor_job, neighbor, neighbor_item)
            ):
                conn.execute(
                    "INSERT INTO background_jobs(job_id,user_id,status,processing,lease_owner,lease_until) VALUES (%s,%s,'running',1,%s,%s)",
                    (job_id, user_id, stale_worker, now + timedelta(minutes=2)),
                )
                conn.execute(
                    "INSERT INTO job_items(job_id,user_id,item_key,url,status,updated_at) VALUES (%s,%s,%s,%s,'processing',%s)",
                    (job_id, user_id, item_key, "https://example.test/" + item_key, now),
                )
                conn.execute(
                    "INSERT INTO job_events(job_id,event_type,message,created_at) VALUES (%s,'claimed','fixture',%s)",
                    (job_id, now),
                )
                conn.execute(
                    "INSERT INTO job_item_leases(job_id,item_key,worker_id,lease_until,updated_at) VALUES (%s,%s,%s,%s,%s)",
                    (job_id, item_key, stale_worker, now + timedelta(minutes=2), now),
                )

        deleted = PostgresJobPrivacyStore(factory).delete_for_user(user_id=owner)
        assert deleted == {"leases": 1, "events": 1, "items": 1, "jobs": 1}

        claims = PostgresJobClaimStore(factory)
        assert claims.heartbeat_item(job_id=owner_job, item_key=owner_item, worker_id=stale_worker) is False
        assert claims.complete_item(
            job_id=owner_job, item_key=owner_item, worker_id=stale_worker, status="completed"
        ) is False

        with factory() as conn:
            assert conn.execute("SELECT COUNT(*) FROM background_jobs WHERE job_id=%s", (owner_job,)).fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM job_items WHERE job_id=%s", (owner_job,)).fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM job_item_leases WHERE job_id=%s", (owner_job,)).fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM job_events WHERE job_id=%s", (owner_job,)).fetchone()[0] == 0
            assert conn.execute("SELECT user_id FROM background_jobs WHERE job_id=%s", (neighbor_job,)).fetchone()[0] == neighbor
            assert conn.execute("SELECT user_id,status FROM job_items WHERE job_id=%s", (neighbor_job,)).fetchone() == (neighbor, "processing")
            assert conn.execute("SELECT worker_id FROM job_item_leases WHERE job_id=%s", (neighbor_job,)).fetchone()[0] == stale_worker
            assert conn.execute("SELECT COUNT(*) FROM job_events WHERE job_id=%s", (neighbor_job,)).fetchone()[0] == 1
    finally:
        with psycopg.connect(base_dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
