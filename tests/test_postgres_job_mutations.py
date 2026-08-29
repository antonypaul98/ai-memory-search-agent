from datetime import datetime, timezone

import pytest

from app.db.postgres_job_mutations import PostgresJobMutationStore


class Cursor:
    def __init__(self, row=None, rowcount=1):
        self.row = row
        self.rowcount = rowcount

    def fetchone(self):
        return self.row


class Connection:
    def __init__(self, *, status_row=("failed",), counts=(0, 2), delete_rowcount=1):
        self.status_row = status_row
        self.counts = list(counts)
        self.delete_rowcount = delete_rowcount
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=()):
        sql = " ".join(query.split())
        self.calls.append((sql, params))
        if sql.startswith("SELECT status FROM background_jobs"):
            return Cursor(self.status_row)
        if sql.startswith("SELECT job_id FROM background_jobs"):
            return Cursor(("job-1",) if self.status_row is not None else None)
        if sql.startswith("SELECT COUNT(*) AS count"):
            return Cursor((self.counts.pop(0),))
        if sql.startswith("DELETE FROM background_jobs"):
            return Cursor(rowcount=self.delete_rowcount)
        return Cursor()


def test_retry_failed_is_tenant_scoped_and_records_event():
    conn = Connection(counts=(0, 3))
    store = PostgresJobMutationStore(lambda: conn)
    now = datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc)

    assert store.retry_failed(job_id="job-1", user_id="user-1", now=now)

    lock_sql, lock_params = conn.calls[0]
    assert "WHERE job_id = %s AND user_id = %s" in lock_sql
    assert "FOR UPDATE" in lock_sql
    assert lock_params == ("job-1", "user-1")

    item_sql, item_params = conn.calls[1]
    assert "status = 'queued'" in item_sql
    assert "status = 'failed'" in item_sql
    assert "user_id = %s" in item_sql
    assert item_params == (now, "job-1", "user-1")

    job_sql, job_params = conn.calls[4]
    assert "status = 'queued'" in job_sql
    assert "paused = FALSE" in job_sql
    assert job_params == (0, 3, "job-1", "user-1")
    assert "'retried', 'Failed items requeued'" in conn.calls[5][0]


def test_retry_cancelled_or_missing_job_fails_closed_without_mutation():
    for status_row in (None, ("cancelled",)):
        conn = Connection(status_row=status_row)
        store = PostgresJobMutationStore(lambda: conn)
        assert not store.retry_failed(job_id="job-1", user_id="user-1")
        assert len(conn.calls) == 1


def test_delete_locks_tenant_job_and_removes_all_queue_state():
    conn = Connection()
    store = PostgresJobMutationStore(lambda: conn)

    assert store.delete_job(job_id="job-1", user_id="user-1")

    lock_sql, lock_params = conn.calls[0]
    assert "WHERE job_id = %s AND user_id = %s" in lock_sql
    assert "FOR UPDATE" in lock_sql
    assert lock_params == ("job-1", "user-1")

    lease_sql, lease_params = conn.calls[1]
    assert "DELETE FROM job_item_leases" in lease_sql
    assert "user_id = %s" in lease_sql
    assert lease_params == ("job-1", "job-1", "user-1")

    assert conn.calls[2] == ("DELETE FROM job_events WHERE job_id = %s", ("job-1",))
    assert conn.calls[3] == (
        "DELETE FROM job_items WHERE job_id = %s AND user_id = %s",
        ("job-1", "user-1"),
    )
    assert conn.calls[4] == (
        "DELETE FROM background_jobs WHERE job_id = %s AND user_id = %s",
        ("job-1", "user-1"),
    )


def test_delete_missing_job_performs_no_destructive_writes():
    conn = Connection(status_row=None)
    store = PostgresJobMutationStore(lambda: conn)

    assert not store.delete_job(job_id="job-1", user_id="user-1")
    assert len(conn.calls) == 1


def test_mutations_validate_identity_and_timezone():
    store = PostgresJobMutationStore(lambda: Connection())
    naive = datetime(2026, 8, 29, 1, 0)

    with pytest.raises(ValueError, match="job_id is required"):
        store.retry_failed(job_id=" ", user_id="user-1")
    with pytest.raises(ValueError, match="user_id is required"):
        store.delete_job(job_id="job-1", user_id=" ")
    with pytest.raises(ValueError, match="timezone-aware"):
        store.retry_failed(job_id="job-1", user_id="user-1", now=naive)
