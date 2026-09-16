"""Real-Postgres acceptance for evidence-backed Home Agent `where is` retrieval."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.postgres_home_image_store import PostgresHomeImageStore
from app.db.postgres_runtime import get_postgres_connection_factory
from app.services.home_agent import HomeAgentQueryService
from app.services.home_agent.image_ingest import ImageObservationBatch, DetectedObject, canonical_id


def test_where_is_uses_latest_qualifying_image_sighting_without_crossing_tenants(monkeypatch):
    if not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"):
        pytest.skip("real Postgres DSN required")

    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    base_dsn = os.environ["MEMORY_AGENT_TEST_POSTGRES_DSN"]
    schema = "home_where_" + uuid4().hex
    with psycopg.connect(base_dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    dsn_alias = "HOME_WHERE_DSN_" + uuid4().hex
    monkeypatch.setenv(dsn_alias, make_conninfo(base_dsn, options=f"-c search_path={schema}"))
    settings = Settings(_env_file=None, postgres_dsn_env=dsn_alias)
    store = PostgresHomeImageStore(get_postgres_connection_factory(settings))
    service = HomeAgentQueryService(store)

    def observe(user_id: str, location: str, when: datetime, confidence: float) -> tuple[str, str, str, bytes]:
        image_bytes = f"{user_id}:{location}:{when.isoformat()}".encode()
        digest = hashlib.sha256(image_bytes).hexdigest()
        frame_id = canonical_id("frame", user_id, digest, "camera-1", location, when.isoformat())
        detection = DetectedObject("keys", confidence, (0.1, 0.2, 0.4, 0.6))
        batch = ImageObservationBatch(
            user_id=user_id, frame_id=frame_id, image_bytes=image_bytes,
            image_sha256=digest, source_id="camera-1", location=location,
            observed_at=when, detector_id="fixture-detector", detections=(detection,),
        )
        assert store.store_image_batch(batch)["stored_observations"] == 1
        observation_id = canonical_id("observation", frame_id, detection.object_class, "[0.1, 0.2, 0.4, 0.6]")
        return observation_id, frame_id, digest, image_bytes

    try:
        owner = "home-where-owner"
        neighbor = "home-where-neighbor"
        older = datetime(2026, 9, 16, 8, 0, tzinfo=timezone.utc)
        newer = datetime(2026, 9, 16, 8, 5, tzinfo=timezone.utc)
        neighbor_time = datetime(2026, 9, 16, 8, 10, tzinfo=timezone.utc)

        observe(owner, "kitchen counter", older, 0.91)
        newest_owner_evidence, newest_owner_frame, newest_owner_digest, newest_owner_bytes = observe(owner, "entry table", newer, 0.96)
        observe(neighbor, "neighbor bedroom", neighbor_time, 0.99)

        answer = service.where_is(user_id=owner, object_name="KEYS", min_confidence=0.90)
        assert answer is not None
        assert answer.object_name == "keys"
        assert answer.location == "entry table"
        assert answer.confidence == 0.96
        assert answer.source_id == "camera-1"
        assert answer.evidence_id == newest_owner_evidence
        assert answer.observed_at == newer.isoformat()
        assert answer.evidence_frame_id == newest_owner_frame
        assert answer.evidence_image_sha256 == newest_owner_digest
        assert answer.evidence_detector_id == "fixture-detector"
        assert service.evidence_image(user_id=owner, answer=answer) == newest_owner_bytes
        assert service.evidence_image(user_id=neighbor, answer=answer) is None
        assert "neighbor bedroom" not in answer.text

        # Raising the trust threshold above all owner sightings must not leak the
        # neighbor's higher-confidence observation.
        assert service.where_is(user_id=owner, object_name="keys", min_confidence=0.98) is None
    finally:
        with psycopg.connect(base_dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
