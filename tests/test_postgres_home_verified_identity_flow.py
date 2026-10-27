"""Real PostgreSQL integration for *synthetic* verifier evidence.

The verifier here is a controlled fixture, not a physical-instance recognizer.
This tests consent -> association -> observed-location query -> revocation,
without asserting a real camera, tag, or person moved an object.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.postgres_home_image_store import PostgresHomeImageStore
from app.db.postgres_runtime import get_postgres_connection_factory
from app.services.home_agent.image_ingest import (
    DetectedObject, ImageObservationBatch, canonical_id,
)
from app.services.home_agent.query_service import HomeAgentQueryService
from app.services.home_agent.verified_identity_ingest import (
    InstanceIdentityConsent, VerifiedInstanceIngestService, VerifiedInstanceProof,
)


class FixtureVerifier:
    """Return only pre-registered synthetic proofs; never infer identity."""

    def __init__(self, proofs):
        self.proofs = proofs

    def verify(self, *, user_id, observation_id, source_id):
        return self.proofs.get((user_id, observation_id, source_id))


def _seed(store, *, user_id, location, observed_at, suffix):
    image_bytes = f"synthetic-{user_id}-{suffix}".encode()
    digest = hashlib.sha256(image_bytes).hexdigest()
    source_id = "consented-camera"
    frame_id = canonical_id(
        "frame", user_id, digest, source_id, location, observed_at.isoformat()
    )
    detection = DetectedObject("keys", 0.96, (0.1, 0.2, 0.4, 0.6))
    batch = ImageObservationBatch(
        user_id=user_id, frame_id=frame_id, image_bytes=image_bytes,
        image_sha256=digest, source_id=source_id, location=location,
        observed_at=observed_at, detector_id="synthetic-detector",
        detections=(detection,),
    )
    assert store.store_image_batch(batch)["stored_observations"] == 1
    return canonical_id(
        "observation", frame_id, detection.object_class, json.dumps(detection.box)
    )


def test_synthetic_verified_identity_flows_through_real_postgres_and_revocation(monkeypatch):
    if not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"):
        pytest.skip("real Postgres DSN required")

    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    base_dsn = os.environ["MEMORY_AGENT_TEST_POSTGRES_DSN"]
    schema = "home_identity_flow_" + uuid4().hex
    with psycopg.connect(base_dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    try:
        dsn_alias = "HOME_IDENTITY_FLOW_DSN_" + uuid4().hex
        monkeypatch.setenv(
            dsn_alias, make_conninfo(base_dsn, options=f"-c search_path={schema}")
        )
        settings = Settings(_env_file=None, postgres_dsn_env=dsn_alias)
        store = PostgresHomeImageStore(get_postgres_connection_factory(settings))
        query = HomeAgentQueryService(store)
        owner, neighbor, source = "house-a", "house-b", "consented-camera"
        base = datetime(2026, 10, 27, 7, tzinfo=timezone.utc)
        first = _seed(store, user_id=owner, location="desk", observed_at=base, suffix="1")
        second = _seed(
            store, user_id=owner, location="kitchen",
            observed_at=base + timedelta(seconds=30), suffix="2",
        )
        _seed(store, user_id=neighbor, location="garage", observed_at=base, suffix="3")

        # Class-only image ingestion cannot produce a verified relocation.
        assert query.observed_location_changes(user_id=owner, object_name="keys") == []
        assert query.observed_location_changes(user_id=neighbor, object_name="keys") == []

        now = datetime.now(timezone.utc)
        expires = store.grant_instance_identity_consent(
            user_id=owner, source_id=source, ttl_seconds=120,
        )
        consent = InstanceIdentityConsent(
            user_id=owner, source_id=source,
            granted_at=now - timedelta(seconds=30), expires_at=expires,
        )
        proofs = {
            (owner, observation, source): VerifiedInstanceProof(
                user_id=owner, observation_id=observation, source_id=source,
                instance_id="keys-physical-1", identity_evidence_id=f"fixture-proof-{i}",
                identity_confidence=0.98,
            )
            for i, observation in enumerate((first, second), start=1)
        }
        service = VerifiedInstanceIngestService(
            verifier=FixtureVerifier(proofs), store=store,
        )
        for observation in (first, second):
            assert service.ingest(
                user_id=owner, observation_id=observation,
                source_id=source, consent=consent, now=now,
            )
        # Replayed observation is idempotent, not another independent proof.
        assert not service.ingest(
            user_id=owner, observation_id=first,
            source_id=source, consent=consent, now=now,
        )

        changes = query.observed_location_changes(user_id=owner, object_name="keys")
        assert len(changes) == 1
        assert (changes[0].from_location, changes[0].to_location) == ("desk", "kitchen")
        assert (changes[0].from_evidence_id, changes[0].to_evidence_id) == (first, second)
        assert (changes[0].from_identity_evidence_id,
                changes[0].to_identity_evidence_id) == ("fixture-proof-1", "fixture-proof-2")
        assert query.observed_location_changes(user_id=neighbor, object_name="keys") == []

        assert store.revoke_instance_identity_consent(user_id=owner, source_id=source) == 2
        assert query.observed_location_changes(user_id=owner, object_name="keys") == []
        # Revocation removes only identity links, not class sightings or other tenants.
        assert len(query.history(user_id=owner, object_name="keys")) == 2
        assert len(query.history(user_id=neighbor, object_name="keys")) == 1
        assert not service.ingest(
            user_id=owner, observation_id=first,
            source_id=source, consent=consent, now=now,
        )
    finally:
        with psycopg.connect(base_dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
