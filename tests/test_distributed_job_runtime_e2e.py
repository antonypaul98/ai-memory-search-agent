"""Real Postgres + Redis validation for the F-35 split-runtime gate.

CI provides disposable services through environment-indirected URLs. Redis carries
only an opaque wake marker; authoritative job identity, tenant data, status, and
leases remain exclusively in Postgres.
"""

from __future__ import annotations

import os
import uuid

import pytest

from app.config import Settings
from app.db.job_store_factory import get_job_store
from app.db.runtime_safety import validate_runtime_topology
from app.services.job_queue_transport import get_job_queue_transport
from app.services.playlist_service import PlaylistVideoEntry


POSTGRES_ENV = "MEMORY_AGENT_TEST_POSTGRES_DSN"
REDIS_ENV = "MEMORY_AGENT_TEST_REDIS_URL"
pytestmark = pytest.mark.skipif(
    not (os.getenv(POSTGRES_ENV) and os.getenv(REDIS_ENV)),
    reason="real Postgres and Redis test services are not configured",
)


def test_split_runtime_wakes_via_redis_and_claims_authoritatively_in_postgres() -> None:
    queue_name = f"memory-agent:test:{uuid.uuid4().hex}:wakeup"
    common = dict(
        jobs_enabled=True,
        job_store_backend="postgres",
        postgres_dsn_env=POSTGRES_ENV,
        postgres_connect_timeout_sec=5,
        job_queue_backend="redis",
        redis_url_env=REDIS_ENV,
        redis_queue_name=queue_name,
        redis_block_timeout_sec=1,
        job_lease_seconds=30,
    )
    api_settings = Settings(worker_mode="api", **common)
    worker_settings = Settings(worker_mode="worker", **common)

    # This exact topology is what the runtime gate protects.
    validate_runtime_topology(api_settings)
    validate_runtime_topology(worker_settings)

    # Independent facades/connections approximate separate API and worker
    # processes while sharing only Postgres + Redis infrastructure.
    api_store = get_job_store(api_settings)
    worker_store = get_job_store(worker_settings)
    api_queue = get_job_queue_transport(api_settings)
    worker_queue = get_job_queue_transport(worker_settings)

    job = api_store.create_playlist_job(
        user_id="distributed-e2e-tenant",
        playlist_id="PL-distributed-e2e",
        playlist_title="Distributed E2E",
        entries=[
            PlaylistVideoEntry(
                video_id="distributed-e2e-video",
                url="https://www.youtube.com/watch?v=distributed-e2e-video",
                title="Distributed E2E Video",
            )
        ],
        reflection=None,
        force_refresh=False,
    )

    try:
        # API sends only an opaque marker after durable creation. Worker consumes
        # that marker, then resolves the real unit of work from Postgres.
        api_queue.notify(1)
        worker_queue.wait()

        claim = worker_store.claim_next_item(worker_id="distributed-e2e-worker")
        assert claim is not None
        job_id, item_key, url = claim
        assert job_id == job.job_id
        assert item_key == "distributed-e2e-video"
        assert url.endswith("distributed-e2e-video")

        # A competing worker cannot claim the leased authoritative row.
        assert worker_store.claim_next_item(worker_id="distributed-e2e-competitor") is None

        assert worker_store.complete_item(
            job_id=job_id,
            item_key=item_key,
            status="completed",
            worker_id="distributed-e2e-worker",
        ) is True

        completed = api_store.get_job(job.job_id, user_id="distributed-e2e-tenant")
        assert completed.status == "completed"
        assert completed.completed == 1
        assert completed.processing == 0
    finally:
        api_store.delete_job(job.job_id, user_id="distributed-e2e-tenant")
