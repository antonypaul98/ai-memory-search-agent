"""Real-Postgres acceptance for Home physical-memory tenant erasure.

This proves retained image bytes and all relational Home memory are erased for one
tenant without touching a neighboring tenant.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.home_physical_privacy import delete_user_home_physical_data
from app.db.postgres_home_image_store import PostgresHomeImageStore
from app.db.postgres_runtime import get_postgres_connection_factory
from app.services.home_agent.image_ingest import ImageObservationBatch, DetectedObject, canonical_id


def test_home_physical_erasure_is_exact_tenant_and_removes_retained_bytes(monkeypatch):
    if not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"):
        pytest.skip("real Postgres DSN required")

    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    base_dsn = os.environ["MEMORY_AGENT_TEST_POSTGRES_DSN"]
    schema = "home_privacy_" + uuid4().hex
    with psycopg.connect(base_dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    dsn_alias = "HOME_PRIVACY_DSN_" + uuid4().hex
    monkeypatch.setenv(dsn_alias, make_conninfo(base_dsn, options=f"-c search_path={schema}"))
    settings = Settings(_env_file=None, postgres_dsn_env=dsn_alias)
    factory = get_postgres_connection_factory(settings)
    store = PostgresHomeImageStore(factory)
    observed_at = datetime(2026, 9, 16, 7, 30, tzinfo=timezone.utc)

    users = ("home-privacy-owner", "home-privacy-neighbor")
    frames: dict[str, str] = {}
    observations: dict[str, str] = {}
    retained: dict[str, bytes] = {}
    try:
        for user_id in users:
            image_bytes = ("private-image-" + user_id).encode()
            digest = hashlib.sha256(image_bytes).hexdigest()
            frame_id = canonical_id("frame", user_id, digest, "camera-1", "kitchen", observed_at.isoformat())
            detection = DetectedObject("keys", 0.94, (0.1, 0.2, 0.4, 0.6))
            batch = ImageObservationBatch(
                user_id=user_id, frame_id=frame_id, image_bytes=image_bytes,
                image_sha256=digest, source_id="camera-1", location="kitchen",
                observed_at=observed_at, detector_id="fixture-detector", detections=(detection,),
            )
            assert store.store_image_batch(batch)["stored_observations"] == 1
            frames[user_id] = frame_id
            retained[user_id] = image_bytes
            observations[user_id] = canonical_id(
                "observation", frame_id, detection.object_class, "[0.1, 0.2, 0.4, 0.6]"
            )

        assert store.get_image(user_id=users[0], frame_id=frames[users[0]]) == retained[users[0]]
        assert store.get_image(user_id=users[1], frame_id=frames[users[1]]) == retained[users[1]]

        assert delete_user_home_physical_data(factory, user_id=users[0]) == {
            "image_observations": 1, "image_evidence": 1,
            "physical_objects": 1, "sightings": 1,
        }
        assert store.get_image(user_id=users[0], frame_id=frames[users[0]]) is None
        assert store.describe_observation(user_id=users[0], observation_id=observations[users[0]]) is None

        # Neighbor evidence, canonical relation, and exact retained bytes survive unchanged.
        assert store.get_image(user_id=users[1], frame_id=frames[users[1]]) == retained[users[1]]
        assert store.describe_observation(user_id=users[1], observation_id=observations[users[1]]) is not None

        # Repeated erasure is idempotent and cannot spill into the neighboring tenant.
        assert delete_user_home_physical_data(factory, user_id=users[0]) == {
            "image_observations": 0, "image_evidence": 0,
            "physical_objects": 0, "sightings": 0,
        }
        assert store.get_image(user_id=users[1], frame_id=frames[users[1]]) == retained[users[1]]
    finally:
        with psycopg.connect(base_dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
