from datetime import datetime, timezone

import pytest

from app.db.postgres_job_controls import PostgresJobControlStore


class Cursor:
    def __init__(self, row=None, rowcount=1):
        self.row = row
        self.rowcount = rowcount

    def fetchone(self):
        return self.row


class Connection:
    def __init__(self, *, status_row=("running",), queued_count=0, update_rowcount=1):
        self.status_row = status_row
        self.queued_count = queued_count
        self.update_rowcount = update_rowcount
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
        if sql.startswith("SELECT COUNT(*) AS count"):
            return Cursor((self.queued_count,))
        if sql.startswith("UPDATE background_jobs"):
            return Cursor(rowcount=self.update_rowcount)
        return Cursor()


def test_pause_is_tenant_scoped_and_records_event():
    conn = Connection()
    store = PostgresJobControlStore(lambda: conn)
    now = datetime(2026, 8, 28, 23, 30, tzinfo=timezone.utc)

    assert store.set_paused(job_id="job-1", user_id="user-1", paused=True, now=now)

    sql, params = conn.calls[0]
    assert "WHERE job_id = %s AND user_id = %s" in sql
    assert params == (True, "job-1", "user-1")
    assert "status NOT IN" not in sql
    assert conn.calls[1][1] == ("job-1", "paused", now)


def test_resume_terminal_job_fails_closed_without_event():
    conn = Connection(update_rowcount=0)
    store = PostgresJobControlStore(lambda: conn)

    assert not store.set_paused(job_id="job-1", user_id="user-1", paused=False)

    assert "status NOT IN ('completed', 'cancelled', 'failed')" in conn.calls[0][0]
    assert len(conn.calls) == 1


def test_cancel_locks_tenant_job_and_only_cancels_queued_items():
    conn = Connection(status_row=("running",), queued_count=0)
    store = PostgresJobControlStore(lambda: conn)
    now = datetime(2026, 8, 28, 23, 45, tzinfo=timezone.utc)

    assert store.cancel_job(job_id="job-1", user_id="user-1", now=now)

    lock_sql, lock_params = conn.calls[0]
    assert "WHERE job_id = %s AND user_id = %s" in lock_sql
    assert "FOR UPDATE" in lock_sql
    assert lock_params == ("job-1", "user-1")
    item_sql = conn.calls[1][0]
    assert "status = 'cancelled'" in item_sql
    assert "status = 'queued'" in item_sql
    assert "user_id = %s" in item_sql
    assert not any("DELETE FROM job_item_leases" in sql for sql, _ in conn.calls)
    final_sql, final_params = conn.calls[3]
    assert "paused = TRUE" in final_sql
    assert final_params[0] == 0
    assert final_params[2:] == ("job-1", "user-1")
    assert "'cancelled', 'Cancelled by user'" in conn.calls[4][0]


def test_cancel_missing_or_terminal_job_performs_no_mutations():
    for status_row in (None, ("completed",), ("cancelled",)):
        conn = Connection(status_row=status_row)
        store = PostgresJobControlStore(lambda: conn)
        assert not store.cancel_job(job_id="job-1", user_id="user-1")
        assert len(conn.calls) == 1


def test_controls_validate_identity_and_timezone():
    store = PostgresJobControlStore(lambda: Connection())
    naive = datetime(2026, 8, 28, 23, 0)

    with pytest.raises(ValueError, match="job_id is required"):
        store.set_paused(job_id=" ", user_id="user-1", paused=True)
    with pytest.raises(ValueError, match="user_id is required"):
        store.cancel_job(job_id="job-1", user_id=" ")
    with pytest.raises(ValueError, match="timezone-aware"):
        store.set_paused(job_id="job-1", user_id="user-1", paused=True, now=naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        store.cancel_job(job_id="job-1", user_id="user-1", now=naive)
