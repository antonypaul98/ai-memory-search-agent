"""Real-Postgres acceptance for Home physical-memory tenant erasure.

Run only when TEST_POSTGRES_DSN is configured.  This proves retained image bytes and
all relational Home memory are erased for one tenant without touching a neighbor.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from app.db.home_physical_privacy import delete_user_home_physical_data
from app.db.postgres_home_image_store import PostgresHomeImageStore
from app.db.postgres_job_repository import get_postgres_connection_factory
from app.services.home_agent.image_ingest import ImageObservationBatch, DetectedObject, canonical_id


pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_DSN"), reason="TEST_POSTGRES_DSN is required"
)


def test_home_physical_erasure_is_exact_tenant_and_removes_retained_bytes(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_POSTGRES_DSN"])
    factory = get_postgres_connection_factory()
    store = PostgresHomeImageStore(factory)
    observed_at = datetime(2026, 9, 16, 7, 30, tzinfo=timezone.utc)

    users = ("home-privacy-owner", "home-privacy-neighbor")
    frames = {}
    observations = {}
    for user_id in users:
        image_bytes = ("private-image-" + user_id).encode()
        import hashlib
        digest = hashlib.sha256(image_bytes).hexdigest()
        frame_id = canonical_id("frame", user_id, digest, "camera-1", "kitchen", observed_at.isoformat())
        detection = DetectedObject("keys", 0.94, (0.1, 0.2, 0.4, 0.6))
        batch = ImageObservationBatch(
            user_id=user_id,
            frame_id=frame_id,
            image_bytes=image_bytes,
            image_sha256=digest,
            source_id="camera-1",
            location="kitchen",
            observed_at=observed_at,
            detector_id="fixture-detector",
            detections=(detection,),
        )
        result = store.store_image_batch(batch)
        assert result["stored_observations"] == 1
        frames[user_id] = frame_id
        observations[user_id] = canonical_id(
            "observation", frame_id, detection.object_class, "[0.1, 0.2, 0.4, 0.6]"
        )

    try:
        assert store.get_image(user_id=users[0], frame_id=frames[users[0]]) is not None
        assert store.get_image(user_id=users[1], frame_id=frames[users[1]]) is not None

        deleted = delete_user_home_physical_data(factory, user_id=users[0])
        assert deleted == {
            "image_observations": 1,
            "image_evidence": 1,
            "physical_objects": 1,
            "sightings": 1,
        }

        assert store.get_image(user_id=users[0], frame_id=frames[users[0]]) is None
        assert store.describe_observation(user_id=users[0], observation_id=observations[users[0]]) is None

        # Neighbor evidence, canonical object relation, and retained bytes survive unchanged.
        assert store.get_image(user_id=users[1], frame_id=frames[users[1]]) is not None
        assert store.describe_observation(user_id=users[1], observation_id=observations[users[1]]) is not None

        # Repeated erasure is safe and cannot spill into the neighboring tenant.
        assert delete_user_home_physical_data(factory, user_id=users[0]) == {
            "image_observations": 0,
            "image_evidence": 0,
            "physical_objects": 0,
            "sightings": 0,
        }
        assert store.get_image(user_id=users[1], frame_id=frames[users[1]]) is not None
    finally:
        for user_id in users:
            delete_user_home_physical_data(factory, user_id=user_id)
