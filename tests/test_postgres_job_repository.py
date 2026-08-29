from datetime import datetime, timezone

import pytest

from app.db.postgres_job_repository import PostgresJobRepository
from app.services.playlist_service import PlaylistVideoEntry


class Cursor:
    def __init__(self, *, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, *, job_rows=None, item_rows=None, event_rows=None, runnable_rows=None):
        self.job_rows = list(job_rows or [])
        self.item_rows = item_rows or []
        self.event_rows = event_rows or []
        self.runnable_rows = runnable_rows or []
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=()):
        sql = " ".join(query.split())
        self.calls.append((sql, params))
        if sql.startswith("SELECT job_id, user_id, job_type"):
            return Cursor(row=self.job_rows.pop(0) if self.job_rows else None)
        if sql.startswith("SELECT item_key, url, title"):
            return Cursor(rows=self.item_rows)
        if sql.startswith("SELECT je.message"):
            return Cursor(rows=self.event_rows)
        if sql.startswith("SELECT job_id FROM background_jobs"):
            return Cursor(rows=self.runnable_rows)
        return Cursor()


def job_row(*, user_id="user-1", created_at=None, started_at=None):
    created_at = created_at or datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc)
    return (
        "job-1",
        user_id,
        "playlist_ingest",
        "PL123",
        "Private playlist title",
        4,
        1,
        1,
        1,
        0,
        1,
        "running",
        None,
        created_at,
        started_at,
        None,
        False,
    )


def test_create_playlist_job_writes_job_items_and_privacy_safe_created_event():
    now = datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc)
    conn = Connection(job_rows=[job_row(created_at=now)])
    store = PostgresJobRepository(lambda: conn)
    entries = [
        PlaylistVideoEntry(video_id="v1", url="https://example.test/private-one", title="Secret one"),
        PlaylistVideoEntry(video_id="v2", url="https://example.test/private-two", title="Secret two"),
    ]

    result = store.create_playlist_job(
        user_id="user-1",
        playlist_id="PL123",
        playlist_title="Private playlist title",
        entries=entries,
        reflection=None,
        force_refresh=True,
        job_id="job-1",
        now=now,
    )

    assert result.job_id == "job-1"
    job_insert = conn.calls[0]
    assert "INSERT INTO background_jobs" in job_insert[0]
    assert job_insert[1][0:4] == ("job-1", "user-1", "PL123", "Private playlist title")
    item_calls = [call for call in conn.calls if call[0].startswith("INSERT INTO job_items")]
    assert len(item_calls) == 2
    assert all(call[1][1] == "user-1" for call in item_calls)

    event_sql, event_params = next(call for call in conn.calls if call[0].startswith("INSERT INTO job_events"))
    assert "'created'" in event_sql
    assert event_params == ("job-1", "Queued 2 videos", now)
    event_text = " ".join(str(value) for value in event_params)
    assert "Private playlist title" not in event_text
    assert "private-one" not in event_text
    assert "Secret one" not in event_text


def test_get_job_is_tenant_scoped_and_uses_explicit_projection():
    created = datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc)
    started = datetime(2026, 8, 29, 1, 1, tzinfo=timezone.utc)
    conn = Connection(job_rows=[job_row(created_at=created, started_at=started)])
    store = PostgresJobRepository(lambda: conn)

    result = store.get_job("job-1", user_id="user-1")

    sql, params = conn.calls[0]
    assert "SELECT *" not in sql
    assert "WHERE job_id = %s AND user_id = %s" in sql
    assert params == ("job-1", "user-1")
    assert result.created_at == created.isoformat()
    assert result.started_at == started.isoformat()
    assert result.processing == 1
    assert result.completed == 1
    assert result.failed == 1
    assert result.estimated_remaining_sec == 16.0


def test_get_job_missing_or_cross_tenant_fails_closed():
    conn = Connection(job_rows=[])
    store = PostgresJobRepository(lambda: conn)

    with pytest.raises(KeyError, match="Job not found"):
        store.get_job("job-1", user_id="other-user")

    assert conn.calls[0][1] == ("job-1", "other-user")


def test_get_job_detail_scopes_items_and_events_to_tenant():
    conn = Connection(
        job_rows=[job_row()],
        item_rows=[("v1", "https://example.test/a", "A", "completed", None)],
        event_rows=[("latest",), ("earliest",)],
    )
    store = PostgresJobRepository(lambda: conn)

    result = store.get_job_detail("job-1", user_id="user-1")

    item_sql, item_params = next(call for call in conn.calls if call[0].startswith("SELECT item_key"))
    assert "WHERE job_id = %s AND user_id = %s" in item_sql
    assert item_params == ("job-1", "user-1")
    event_sql, event_params = next(call for call in conn.calls if call[0].startswith("SELECT je.message"))
    assert "EXISTS" in event_sql
    assert "bj.user_id = %s" in event_sql
    assert event_params == ("job-1", "user-1")
    assert result.items[0].item_key == "v1"
    assert result.events == ["earliest", "latest"]


def test_list_runnable_jobs_supports_global_worker_and_tenant_scoped_views():
    global_conn = Connection(runnable_rows=[("job-1",), ("job-2",)])
    global_store = PostgresJobRepository(lambda: global_conn)
    assert global_store.list_runnable_jobs() == ["job-1", "job-2"]
    global_sql, global_params = global_conn.calls[0]
    assert "paused = FALSE" in global_sql
    assert "user_id = %s" not in global_sql
    assert global_params == ()

    tenant_conn = Connection(runnable_rows=[("job-2",)])
    tenant_store = PostgresJobRepository(lambda: tenant_conn)
    assert tenant_store.list_runnable_jobs(user_id="user-2") == ["job-2"]
    tenant_sql, tenant_params = tenant_conn.calls[0]
    assert "AND user_id = %s" in tenant_sql
    assert tenant_params == ("user-2",)


def test_repository_validates_identity_and_timezone():
    store = PostgresJobRepository(lambda: Connection())
    naive = datetime(2026, 8, 29, 1, 0)

    with pytest.raises(ValueError, match="user_id is required"):
        store.get_job("job-1", user_id=" ")
    with pytest.raises(ValueError, match="playlist_id is required"):
        store.create_playlist_job(
            user_id="user-1",
            playlist_id=" ",
            playlist_title="title",
            entries=[],
            reflection=None,
            force_refresh=False,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        store.create_playlist_job(
            user_id="user-1",
            playlist_id="PL123",
            playlist_title="title",
            entries=[],
            reflection=None,
            force_refresh=False,
            job_id="job-1",
            now=naive,
        )


def test_get_job_rejects_naive_postgres_timestamps():
    row = list(job_row())
    row[13] = datetime(2026, 8, 29, 1, 0)
    store = PostgresJobRepository(lambda: Connection(job_rows=[tuple(row)]))

    with pytest.raises(ValueError, match="timestamps must be timezone-aware"):
        store.get_job("job-1", user_id="user-1")
