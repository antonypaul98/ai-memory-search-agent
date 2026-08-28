from datetime import datetime, timezone

import pytest

from app.db.postgres_job_claims import ClaimedJobItem, PostgresJobClaimStore


class Cursor:
    def __init__(self, row=None, rowcount=1):
        self.row = row
        self.rowcount = rowcount

    def fetchone(self):
        return self.row


class Connection:
    def __init__(
        self,
        claim_row=None,
        *,
        heartbeat_rowcount=1,
        completion_rowcount=1,
        remaining_count=0,
        finish_rowcount=1,
    ):
        self.claim_row = claim_row
        self.heartbeat_rowcount = heartbeat_rowcount
        self.completion_rowcount = completion_rowcount
        self.remaining_count = remaining_count
        self.finish_rowcount = finish_rowcount
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=()):
        sql = " ".join(query.split())
        self.calls.append((sql, params))
        if "WITH candidate AS" in sql:
            return Cursor(self.claim_row)
        if sql.startswith("UPDATE job_item_leases jl"):
            return Cursor(rowcount=self.heartbeat_rowcount)
        if sql.startswith("UPDATE job_items ji") and "jl.worker_id = %s" in sql:
            return Cursor(rowcount=self.completion_rowcount)
        if sql.startswith("SELECT COUNT(*) AS count"):
            return Cursor((self.remaining_count,))
        if sql.startswith("UPDATE background_jobs") and "finished_at = %s" in sql:
            return Cursor(rowcount=self.finish_rowcount)
        return Cursor()


def test_claim_uses_skip_locked_and_updates_lease_and_counters():
    conn = Connection(("job-1", "item-1", "memory://item-1", "queued"))
    store = PostgresJobClaimStore(lambda: conn, lease_seconds=90)
    now = datetime(2026, 8, 28, 21, 0, tzinfo=timezone.utc)

    claimed = store.claim_next_item(worker_id="worker-a", user_id="user-1", now=now)

    assert claimed == ClaimedJobItem("job-1", "item-1", "memory://item-1")
    claim_sql, claim_params = conn.calls[0]
    assert "FOR UPDATE OF ji SKIP LOCKED" in claim_sql
    assert "AND ji.user_id = %s" in claim_sql
    assert claim_params[2] == "user-1"
    assert claim_params[-1] == now
    assert "ON CONFLICT (job_id, item_key) DO UPDATE" in conn.calls[1][0]
    assert "processing = processing + 1" in conn.calls[2][0]
    assert "queued = GREATEST(0, queued - 1)" in conn.calls[2][0]


def test_reclaimed_item_does_not_double_count_aggregates():
    conn = Connection(("job-2", "item-2", "memory://item-2", "processing"))
    store = PostgresJobClaimStore(lambda: conn)
    now = datetime(2026, 8, 28, 21, 0, tzinfo=timezone.utc)

    claimed = store.claim_next_item(worker_id="worker-b", now=now)

    assert claimed and claimed.job_id == "job-2"
    assert "processing = processing + 1" not in conn.calls[2][0]
    assert "'reclaimed'" in conn.calls[3][0]
    assert conn.calls[3][1] == ("job-2", now)


def test_empty_claim_performs_no_follow_up_writes():
    conn = Connection()
    store = PostgresJobClaimStore(lambda: conn)

    assert store.claim_next_item(worker_id="worker-a") is None
    assert len(conn.calls) == 1


def test_claim_rejects_blank_worker_and_naive_clock():
    store = PostgresJobClaimStore(lambda: Connection())

    with pytest.raises(ValueError, match="worker_id is required"):
        store.claim_next_item(worker_id=" ")
    with pytest.raises(ValueError, match="timezone-aware"):
        store.claim_next_item(worker_id="worker-a", now=datetime(2026, 8, 28, 21, 0))


def test_schema_uses_timestamptz_for_lease_expiry():
    conn = Connection()
    store = PostgresJobClaimStore(lambda: conn)

    store.ensure_schema()

    assert "lease_until TIMESTAMPTZ NOT NULL" in conn.calls[0][0]
    assert "idx_job_item_leases_expiry" in conn.calls[1][0]


def test_heartbeat_requires_current_worker_and_extends_authoritative_state():
    conn = Connection()
    store = PostgresJobClaimStore(lambda: conn, lease_seconds=90)
    now = datetime(2026, 8, 28, 22, 0, tzinfo=timezone.utc)

    assert store.heartbeat_item(job_id="job-1", item_key="item-1", worker_id="worker-a", now=now)

    lease_sql, lease_params = conn.calls[0]
    assert "jl.worker_id = %s" in lease_sql
    assert lease_params[2:] == ("job-1", "item-1", "worker-a")
    assert lease_params[0].timestamp() == now.timestamp() + 90
    assert "status = 'processing'" in conn.calls[1][0]
    assert "lease_owner = %s" in conn.calls[2][0]


def test_stale_worker_heartbeat_fails_closed_without_follow_up_writes():
    conn = Connection(heartbeat_rowcount=0)
    store = PostgresJobClaimStore(lambda: conn)

    assert not store.heartbeat_item(job_id="job-1", item_key="item-1", worker_id="stale-worker")
    assert len(conn.calls) == 1


def test_complete_item_requires_authoritative_lease_and_updates_counters():
    conn = Connection(remaining_count=1)
    store = PostgresJobClaimStore(lambda: conn)
    now = datetime(2026, 8, 28, 22, 15, tzinfo=timezone.utc)

    assert store.complete_item(
        job_id="job-1",
        item_key="item-1",
        status="failed",
        error="bounded internal failure",
        worker_id="worker-a",
        now=now,
    )

    finalize_sql, finalize_params = conn.calls[0]
    assert "ji.status = 'processing'" in finalize_sql
    assert "jl.worker_id = %s" in finalize_sql
    assert finalize_params[-1] == "worker-a"
    assert "DELETE FROM job_item_leases" in conn.calls[1][0]
    counter_sql = conn.calls[2][0]
    assert "processing = GREATEST(0, processing - 1)" in counter_sql
    assert "failed = failed + 1" in counter_sql
    assert not any("finished_at" in sql for sql, _ in conn.calls)


def test_stale_worker_completion_fails_closed_without_counter_mutation():
    conn = Connection(completion_rowcount=0)
    store = PostgresJobClaimStore(lambda: conn)

    accepted = store.complete_item(
        job_id="job-1",
        item_key="item-1",
        status="completed",
        worker_id="stale-worker",
    )

    assert not accepted
    assert len(conn.calls) == 1


def test_last_item_completes_job_but_never_resurrects_cancelled_job():
    conn = Connection(remaining_count=0, finish_rowcount=0)
    store = PostgresJobClaimStore(lambda: conn)

    assert store.complete_item(
        job_id="job-cancelled",
        item_key="item-1",
        status="skipped",
        worker_id="worker-a",
    )

    finish_calls = [(sql, params) for sql, params in conn.calls if "finished_at = %s" in sql]
    assert len(finish_calls) == 1
    assert "status <> 'cancelled'" in finish_calls[0][0]
    assert not any("'completed', 'Job finished'" in sql for sql, _ in conn.calls)


def test_last_item_records_terminal_event_when_job_finishes():
    conn = Connection(remaining_count=0, finish_rowcount=1)
    store = PostgresJobClaimStore(lambda: conn)

    assert store.complete_item(
        job_id="job-1",
        item_key="item-1",
        status="completed",
        worker_id="worker-a",
    )

    assert any("'completed', 'Job finished'" in sql for sql, _ in conn.calls)


def test_worker_lifecycle_rejects_invalid_identity_status_and_naive_clock():
    store = PostgresJobClaimStore(lambda: Connection())
    naive = datetime(2026, 8, 28, 22, 0)

    with pytest.raises(ValueError, match="worker_id is required"):
        store.heartbeat_item(job_id="j", item_key="i", worker_id=" ")
    with pytest.raises(ValueError, match="timezone-aware"):
        store.heartbeat_item(job_id="j", item_key="i", worker_id="w", now=naive)
    with pytest.raises(ValueError, match="completed, skipped, or failed"):
        store.complete_item(job_id="j", item_key="i", status="processing", worker_id="w")
    with pytest.raises(ValueError, match="timezone-aware"):
        store.complete_item(job_id="j", item_key="i", status="completed", worker_id="w", now=naive)
