"""Real image decoding and Postgres persistence; detector is an explicit fixture."""
from dataclasses import replace
from datetime import timedelta
import os
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.postgres_home_image_store import PostgresHomeImageStore
from app.services.home_agent.image_ingest import DetectedObject, HomeImageIngestService
from app.services.home_agent.observation_ingest import ObservationConsent, PHYSICAL_OBSERVATION_SCOPE
from app.services.home_agent.query_service import HomeAgentQueryService
from tests.test_home_agent_image_ingest import NOW, image_bytes

pytestmark = pytest.mark.skipif(not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"), reason="real Postgres DSN required")


class FixtureDetector:
    detector_id = "fixture-not-a-trained-detector"
    def detect(self, image):
        assert image.size == (24, 16)
        return [DetectedObject("keys", .91, (.1, .1, .5, .5)),
                DetectedObject("wallet", .88, (.5, .5, .9, .9))]


def test_image_to_last_seen_with_restart_dedup_conflict_and_tenant_isolation():
    factory = get_postgres_connection_factory(Settings(postgres_dsn_env="MEMORY_AGENT_TEST_POSTGRES_DSN"))
    store = PostgresHomeImageStore(factory)
    ingest = HomeImageIngestService(store, FixtureDetector())
    owner, other = "image-" + uuid4().hex, "image-" + uuid4().hex
    frames = []
    try:
        for tenant, location, delta in [(owner, "office desk", 180), (owner, "kitchen counter", 18),
                                        (other, "bedroom", 1)]:
            kwargs = dict(user_id=tenant, image_bytes=image_bytes(), source_id="phone", location=location,
                          observed_at=NOW - timedelta(minutes=delta), now=NOW,
                          consent=ObservationConsent(tenant, "phone", PHYSICAL_OBSERVATION_SCOPE, NOW))
            result = ingest.ingest(**kwargs)
            frames.append((tenant, result["frame_id"]))
            assert result["stored_observations"] == 2
            assert ingest.ingest(**kwargs)["stored_observations"] == 0
        restarted = PostgresHomeImageStore(factory)
        query = HomeAgentQueryService(restarted)
        latest = query.where_is(user_id=owner, object_name="keys")
        assert latest.location == "kitchen counter"
        assert latest.observed_at == (NOW - timedelta(minutes=18)).isoformat()
        assert latest.confidence == .91
        detail = restarted.describe_observation(user_id=owner, observation_id=latest.evidence_id)
        assert detail["identity_kind"] == "class"
        assert detail["object_class"] == "keys"
        assert restarted.get_image(user_id=owner, frame_id=detail["frame_id"])
        assert restarted.get_image(user_id=other, frame_id=detail["frame_id"]) is None
        assert restarted.describe_observation(user_id=other, observation_id=latest.evidence_id) is None
        assert restarted.delete_image(user_id=other, frame_id=detail["frame_id"]) is False
        assert query.where_is(user_id=other, object_name="keys").location == "bedroom"
        history = query.history(user_id=owner, object_name="keys")
        assert len(history) == 2
        # Same timestamp with conflicting locations stays inspectable in history.
        conflict = ingest.ingest(user_id=owner, image_bytes=image_bytes(), source_id="second-camera",
            location="entrance", observed_at=NOW-timedelta(minutes=18), now=NOW,
            consent=ObservationConsent(owner, "second-camera", PHYSICAL_OBSERVATION_SCOPE, NOW))
        frames.append((owner, conflict["frame_id"]))
        assert len(query.history(user_id=owner, object_name="keys")) == 3
        assert restarted.delete_image(user_id=owner, frame_id=conflict["frame_id"])
        assert restarted.delete_image(user_id=owner, frame_id=detail["frame_id"])
        assert query.where_is(user_id=owner, object_name="keys").location == "office desk"
    finally:
        for tenant, frame_id in frames:
            store.delete_image(user_id=tenant, frame_id=frame_id)


def test_image_batch_rolls_back_all_evidence_and_objects_on_failure():
    from contextlib import contextmanager
    factory = get_postgres_connection_factory(Settings(postgres_dsn_env="MEMORY_AGENT_TEST_POSTGRES_DSN"))
    owner = "rollback-image-" + uuid4().hex

    class RejectObservation:
        def __init__(self, conn):
            self.conn = conn
        def execute(self, sql, params=()):
            if "INSERT INTO home_image_observations" in sql:
                raise RuntimeError("injected observation failure")
            return self.conn.execute(sql, params)

    @contextmanager
    def failing_factory():
        with factory() as conn:
            yield RejectObservation(conn)

    store = PostgresHomeImageStore(failing_factory)
    ingest = HomeImageIngestService(store, FixtureDetector())
    kwargs = dict(user_id=owner, image_bytes=image_bytes(), source_id="phone", location="office",
                  observed_at=NOW-timedelta(minutes=1), now=NOW,
                  consent=ObservationConsent(owner, "phone", PHYSICAL_OBSERVATION_SCOPE, NOW))
    with pytest.raises(RuntimeError, match="injected observation failure"):
        ingest.ingest(**kwargs)
    with factory() as conn:
        for table in ("home_image_evidence", "home_physical_objects", "home_object_sightings", "home_image_observations"):
            assert conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE user_id=%s", (owner,)).fetchone()["n"] == 0
    good = PostgresHomeImageStore(factory)
    result = HomeImageIngestService(good, FixtureDetector()).ingest(**kwargs)
    assert result["stored_observations"] == 2
    assert good.delete_image(user_id=owner, frame_id=result["frame_id"])
