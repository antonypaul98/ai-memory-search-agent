"""Real-Postgres regression coverage for the GAP-02 durable job-store cutover.

The test is skipped outside CI/local environments that explicitly provide a test
DSN.  It never embeds production credentials and exercises only disposable job
records created by this test.
"""

from __future__ import annotations

import os

import pytest

from app.config import Settings
from app.db.job_store_factory import get_job_execution_context, get_job_store
from app.models.reflection import ReflectionInput
from app.services.playlist_service import PlaylistVideoEntry


TEST_DSN_ENV = "MEMORY_AGENT_TEST_POSTGRES_DSN"
pytestmark = pytest.mark.skipif(
    not os.getenv(TEST_DSN_ENV),
    reason=f"{TEST_DSN_ENV} is not configured",
)


def test_real_postgres_job_lifecycle_and_tenant_isolation() -> None:
    settings = Settings(
        job_store_backend="postgres",
        postgres_dsn_env=TEST_DSN_ENV,
        postgres_connect_timeout_sec=5,
        job_lease_seconds=30,
        jobs_enabled=True,
    )
    store = get_job_store(settings)

    user_id = "postgres-e2e-tenant"
    other_user_id = "postgres-e2e-other-tenant"
    reflection = ReflectionInput(
        save_reason="reference",
        goal="Validate Postgres durable job state",
        reflection_note="CI-only integration record",
    )
    job = store.create_playlist_job(
        user_id=user_id,
        playlist_id="PL-postgres-e2e",
        playlist_title="Postgres E2E",
        entries=[
            PlaylistVideoEntry(
                video_id="postgres-e2e-video",
                url="https://www.youtube.com/watch?v=postgres-e2e-video",
                title="Postgres E2E Video",
            )
        ],
        reflection=reflection,
        force_refresh=True,
    )

    try:
        created = store.get_job(job.job_id, user_id=user_id)
        assert created.status == "queued"
        assert created.queued == 1
        assert created.processing == 0

        with pytest.raises(KeyError):
            store.get_job(job.job_id, user_id=other_user_id)

        context = get_job_execution_context(settings, job.job_id)
        assert context.user_id == user_id
        assert context.force_refresh is True
        assert context.reflection is not None
        assert context.reflection.goal == "Validate Postgres durable job state"

        claim = store.claim_next_item(worker_id="postgres-e2e-worker")
        assert claim is not None
        claimed_job_id, item_key, url = claim
        assert claimed_job_id == job.job_id
        assert item_key == "postgres-e2e-video"
        assert url.endswith("postgres-e2e-video")

        assert store.heartbeat_item(
            job_id=job.job_id,
            item_key=item_key,
            worker_id="stale-worker",
        ) is False
        assert store.heartbeat_item(
            job_id=job.job_id,
            item_key=item_key,
            worker_id="postgres-e2e-worker",
        ) is True

        assert store.complete_item(
            job_id=job.job_id,
            item_key=item_key,
            status="completed",
            worker_id="stale-worker",
        ) is False
        assert store.complete_item(
            job_id=job.job_id,
            item_key=item_key,
            status="completed",
            worker_id="postgres-e2e-worker",
        ) is True

        completed = store.get_job(job.job_id, user_id=user_id)
        assert completed.status == "completed"
        assert completed.queued == 0
        assert completed.processing == 0
        assert completed.completed == 1

        detail = store.get_job_detail(job.job_id, user_id=user_id)
        assert len(detail.items) == 1
        assert detail.items[0].status == "completed"
    finally:
        store.delete_job(job.job_id, user_id=user_id)

    with pytest.raises(KeyError):
        store.get_job(job.job_id, user_id=user_id)
