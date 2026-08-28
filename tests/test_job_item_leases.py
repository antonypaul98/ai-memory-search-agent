"""Regression tests for F-35 per-item claim leases and stale-worker safety."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.config import Settings
from app.db.job_store import JobStore
from app.db.schema import get_connection
from app.services.event_bus import EventBus
from app.services.job_worker import JobWorker
from app.services.playlist_service import PlaylistVideoEntry


def _create_job(store: JobStore, *, user_id: str = "tenant-a"):
    return store.create_playlist_job(
        user_id=user_id,
        playlist_id="PLlease",
        playlist_title="Lease test",
        entries=[
            PlaylistVideoEntry(
                video_id="video-1",
                url="https://www.youtube.com/watch?v=video-1",
                title="Video 1",
            )
        ],
        reflection=None,
        force_refresh=False,
    )


def _expire_lease(settings: Settings, job_id: str, item_key: str) -> None:
    expired = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    with get_connection(settings) as conn:
        conn.execute(
            """
            UPDATE job_item_leases SET lease_until = ?, updated_at = ?
            WHERE job_id = ? AND item_key = ?
            """,
            (expired, expired, job_id, item_key),
        )


def test_competing_worker_cannot_take_live_claim(test_settings: Settings) -> None:
    settings = test_settings.model_copy(update={"job_lease_seconds": 60})
    store = JobStore(settings)
    job = _create_job(store)

    assert store.claim_next_item(worker_id="worker-a") == (
        job.job_id,
        "video-1",
        "https://www.youtube.com/watch?v=video-1",
    )
    assert store.claim_next_item(worker_id="worker-b") is None

    current = store.get_job(job.job_id, user_id="tenant-a")
    assert current.queued == 0
    assert current.processing == 1


def test_expired_claim_is_recovered_without_double_counting(test_settings: Settings) -> None:
    settings = test_settings.model_copy(update={"job_lease_seconds": 60})
    store = JobStore(settings)
    job = _create_job(store)
    assert store.claim_next_item(worker_id="worker-a") is not None
    _expire_lease(settings, job.job_id, "video-1")

    assert store.claim_next_item(worker_id="worker-b") == (
        job.job_id,
        "video-1",
        "https://www.youtube.com/watch?v=video-1",
    )

    current = store.get_job(job.job_id, user_id="tenant-a")
    assert current.queued == 0
    assert current.processing == 1
    with get_connection(settings) as conn:
        lease = conn.execute(
            "SELECT worker_id FROM job_item_leases WHERE job_id = ? AND item_key = ?",
            (job.job_id, "video-1"),
        ).fetchone()
        events = conn.execute(
            "SELECT COUNT(*) AS c FROM job_events WHERE job_id = ? AND event_type = 'reclaimed'",
            (job.job_id,),
        ).fetchone()["c"]
    assert lease["worker_id"] == "worker-b"
    assert events == 1


def test_heartbeat_is_owner_scoped(test_settings: Settings) -> None:
    settings = test_settings.model_copy(update={"job_lease_seconds": 60})
    store = JobStore(settings)
    job = _create_job(store)
    assert store.claim_next_item(worker_id="worker-a") is not None

    with get_connection(settings) as conn:
        before = conn.execute(
            "SELECT lease_until FROM job_item_leases WHERE job_id = ? AND item_key = ?",
            (job.job_id, "video-1"),
        ).fetchone()["lease_until"]

    assert store.heartbeat_item(
        job_id=job.job_id, item_key="video-1", worker_id="worker-b"
    ) is False
    assert store.heartbeat_item(
        job_id=job.job_id, item_key="video-1", worker_id="worker-a"
    ) is True

    with get_connection(settings) as conn:
        lease = conn.execute(
            "SELECT worker_id, lease_until FROM job_item_leases WHERE job_id = ? AND item_key = ?",
            (job.job_id, "video-1"),
        ).fetchone()
    assert lease["worker_id"] == "worker-a"
    assert lease["lease_until"] >= before


def test_stale_worker_cannot_finalize_reclaimed_item(test_settings: Settings) -> None:
    settings = test_settings.model_copy(update={"job_lease_seconds": 60})
    store = JobStore(settings)
    job = _create_job(store)
    assert store.claim_next_item(worker_id="worker-a") is not None
    _expire_lease(settings, job.job_id, "video-1")
    assert store.claim_next_item(worker_id="worker-b") is not None

    assert store.complete_item(
        job_id=job.job_id,
        item_key="video-1",
        status="completed",
        worker_id="worker-a",
    ) is False
    mid = store.get_job(job.job_id, user_id="tenant-a")
    assert mid.processing == 1
    assert mid.completed == 0

    assert store.complete_item(
        job_id=job.job_id,
        item_key="video-1",
        status="completed",
        worker_id="worker-b",
    ) is True
    done = store.get_job(job.job_id, user_id="tenant-a")
    assert done.processing == 0
    assert done.completed == 1
    assert done.status == "completed"


def test_processing_item_without_lease_is_recoverable_after_stale_window(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(update={"job_lease_seconds": 60})
    store = JobStore(settings)
    job = _create_job(store)
    assert store.claim_next_item(worker_id="legacy-worker") is not None
    stale = (datetime.now(timezone.utc) - timedelta(seconds=61)).isoformat()
    with get_connection(settings) as conn:
        conn.execute(
            "DELETE FROM job_item_leases WHERE job_id = ? AND item_key = ?",
            (job.job_id, "video-1"),
        )
        conn.execute(
            "UPDATE job_items SET updated_at = ? WHERE job_id = ? AND item_key = ?",
            (stale, job.job_id, "video-1"),
        )

    assert store.claim_next_item(worker_id="worker-new") is not None
    current = store.get_job(job.job_id, user_id="tenant-a")
    assert current.processing == 1
    assert current.queued == 0


def test_worker_completion_carries_claim_owner(test_settings: Settings) -> None:
    settings = test_settings.model_copy(update={"job_lease_seconds": 60})
    worker = JobWorker(settings)
    worker._store = MagicMock()
    worker._store.complete_item.return_value = True
    worker._ingest = MagicMock()
    worker._ingest.ingest_single_url.return_value = SimpleNamespace(
        skipped=False,
        success=True,
        error=None,
    )

    # Helpers read the job row, so make a real row available in the same DB.
    store = JobStore(settings)
    job = _create_job(store)
    worker._process_item(
        job.job_id,
        "video-1",
        "https://www.youtube.com/watch?v=video-1",
        worker_id="worker-owner",
    )

    kwargs = worker._store.complete_item.call_args.kwargs
    assert kwargs["worker_id"] == "worker-owner"
    assert kwargs["status"] == "completed"

    events, _ = EventBus(settings).list_events(
        user_id="tenant-a", event_type="job.state_changed"
    )
    assert len(events) == 1
    assert events[0].actor == "worker"
    assert events[0].aggregate_id == job.job_id
    assert events[0].payload == {
        "action": "item_finalized",
        "item_status": "completed",
    }
    serialized = str(events[0].payload)
    assert "youtube.com" not in serialized
    assert "Video 1" not in serialized
    assert "video-1" not in serialized


def test_stale_worker_completion_does_not_emit_audit_event(test_settings: Settings) -> None:
    settings = test_settings.model_copy(update={"job_lease_seconds": 60})
    worker = JobWorker(settings)
    worker._store = MagicMock()
    worker._store.complete_item.return_value = False
    worker._ingest = MagicMock()
    worker._ingest.ingest_single_url.return_value = SimpleNamespace(
        skipped=False,
        success=True,
        error=None,
    )

    store = JobStore(settings)
    job = _create_job(store)
    worker._process_item(
        job.job_id,
        "private-item-key",
        "https://private.example/secret",
        worker_id="stale-worker",
    )

    events, _ = EventBus(settings).list_events(
        user_id="tenant-a", event_type="job.state_changed"
    )
    assert events == []


def test_audit_failure_cannot_rewrite_success_as_failed(test_settings: Settings) -> None:
    settings = test_settings.model_copy(update={"job_lease_seconds": 60})
    worker = JobWorker(settings)
    worker._store = MagicMock()
    worker._store.complete_item.return_value = True
    worker._ingest = MagicMock()
    worker._ingest.ingest_single_url.return_value = SimpleNamespace(
        skipped=False,
        success=True,
        error=None,
    )

    store = JobStore(settings)
    job = _create_job(store)
    with patch("app.services.job_worker.EventBus.emit", side_effect=RuntimeError("audit down")):
        worker._process_item(
            job.job_id,
            "video-1",
            "https://www.youtube.com/watch?v=video-1",
            worker_id="worker-owner",
        )

    assert worker._store.complete_item.call_count == 1
    kwargs = worker._store.complete_item.call_args.kwargs
    assert kwargs["status"] == "completed"
    assert "error" not in kwargs
