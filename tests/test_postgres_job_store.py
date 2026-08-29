from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.exceptions import AppError
from app.db.postgres_job_store import PostgresJobStore
from app.models.job import BackgroundJob


def _store() -> PostgresJobStore:
    store = PostgresJobStore(lambda: None)
    store._repository = MagicMock()
    store._claims = MagicMock()
    store._controls = MagicMock()
    store._mutations = MagicMock()
    return store


def _job(status: str = "running") -> BackgroundJob:
    return BackgroundJob(
        job_id="job-1",
        user_id="user-1",
        job_type="playlist_ingest",
        playlist_id="pl-1",
        status=status,
        created_at="2026-08-29T00:00:00+00:00",
    )


def test_claim_adapts_postgres_claim_to_existing_tuple_contract() -> None:
    store = _store()
    store._claims.claim_next_item.return_value = SimpleNamespace(
        job_id="job-1", item_key="video-1", url="https://example.invalid/video-1"
    )

    assert store.claim_next_item(worker_id="worker-1") == (
        "job-1",
        "video-1",
        "https://example.invalid/video-1",
    )


def test_claim_preserves_empty_queue() -> None:
    store = _store()
    store._claims.claim_next_item.return_value = None

    assert store.claim_next_item(worker_id="worker-1") is None


def test_postgres_completion_requires_authoritative_worker_identity() -> None:
    store = _store()

    with pytest.raises(ValueError, match="worker_id is required"):
        store.complete_item(job_id="job-1", item_key="video-1", status="completed")

    store._claims.complete_item.assert_not_called()


def test_resume_terminal_job_matches_sqlite_fail_closed_contract() -> None:
    store = _store()
    store._repository.get_job.return_value = _job("completed")

    with pytest.raises(AppError, match="Cannot resume a completed job"):
        store.set_paused("job-1", user_id="user-1", paused=False)

    store._controls.set_paused.assert_not_called()


def test_cancel_terminal_job_is_idempotent() -> None:
    store = _store()
    current = _job("cancelled")
    store._repository.get_job.return_value = current

    assert store.cancel_job("job-1", user_id="user-1") is current
    store._controls.cancel_job.assert_not_called()


def test_retry_cancelled_job_matches_sqlite_contract() -> None:
    store = _store()
    store._repository.get_job.return_value = _job("cancelled")

    with pytest.raises(AppError, match="Cannot retry a cancelled job"):
        store.retry_failed("job-1", user_id="user-1")

    store._mutations.retry_failed.assert_not_called()


def test_delete_establishes_tenant_ownership_before_mutation() -> None:
    store = _store()
    store._repository.get_job.side_effect = KeyError("Job not found: job-1")

    with pytest.raises(KeyError):
        store.delete_job("job-1", user_id="wrong-user")

    store._mutations.delete_job.assert_not_called()


def test_successful_pause_returns_fresh_authoritative_job() -> None:
    store = _store()
    before = _job("running")
    after = before.model_copy(update={"paused": True})
    store._repository.get_job.side_effect = [before, after]
    store._controls.set_paused.return_value = True

    result = store.set_paused("job-1", user_id="user-1", paused=True)

    assert result.paused is True
    store._controls.set_paused.assert_called_once_with(
        job_id="job-1", user_id="user-1", paused=True
    )
