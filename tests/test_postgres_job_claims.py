from datetime import datetime, timezone

import pytest

from app.db.postgres_job_claims import ClaimedJobItem, PostgresJobClaimStore


class Cursor:
    def __init__(self, row=None):
        self.row = row
        self.rowcount = 1

    def fetchone(self):
        return self.row


class Connection:
    def __init__(self, claim_row=None):
        self.claim_row = claim_row
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
