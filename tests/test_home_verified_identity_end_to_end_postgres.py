"""Synthetic verifier -> consented PostgreSQL -> observed-change integration.

This uses deliberately fabricated identity proofs. Passing it does NOT verify
real physical-instance recognition, camera tracking, or hardware acceptance.
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


@pytest.fixture
def store_with_real_postgres(monkeypatch):
    dsn = os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("real PostgreSQL DSN required")
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    schema = "home_identity_flow_" + uuid4().hex
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    alias = "HOME_IDENTITY_FLOW_DSN_" + uuid4().hex
    monkeypatch.setenv(alias, make_conninfo(dsn, options=f"-c search_path={schema}"))
    factory = get_postgres_connection_factory(
        Settings(_env_file=None, postgres_dsn_env=alias)
    )
    try:
        yield PostgresHomeImageStore(factory)
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                sql.Identifier(schema)
            ))


def _sighting(store, *, suffix: str, location: str, observed_at: datetime) -> str:
    user_id, source_id = "house-a", "camera-1"
    image_bytes = f"synthetic:{suffix}:{location}".encode()
    digest = hashlib.sha256(image_bytes).hexdigest()
    frame_id = canonical_id("frame", user_id, digest, source_id, location, suffix)
    detection = DetectedObject("keys", 0.97, (0.1, 0.2, 0.4, 0.6))
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


class SyntheticVerifier:
    """Test double, not a deployable identity recognizer."""

    def __init__(self, proofs):
        self.proofs = proofs

    def verify(self, *, user_id: str, observation_id: str, source_id: str):
        return self.proofs.get((user_id, observation_id, source_id))


def test_synthetic_identity_evidence_round_trip_and_revocation(store_with_real_postgres):
    store = store_with_real_postgres
    now = datetime.now(timezone.utc)
    pregrant = _sighting(
        store, suffix="before-grant", location="entryway",
        observed_at=now - timedelta(minutes=2),
    )

    proofs = {("house-a", pregrant, "camera-1"): VerifiedInstanceProof(
        user_id="house-a", observation_id=pregrant, source_id="camera-1",
        instance_id="keys-a", identity_evidence_id="synthetic-proof-pregrant",
        identity_confidence=0.98,
    )}

    verifier = SyntheticVerifier(proofs)
    service = VerifiedInstanceIngestService(verifier=verifier, store=store)
    consent = InstanceIdentityConsent(
        user_id="house-a", source_id="camera-1",
        granted_at=now - timedelta(seconds=5),
        expires_at=now + timedelta(minutes=5),
    )

    # Neither a caller-provided consent object nor a later grant can authorize
    # identity linking of a sighting captured before server consent.
    assert not service.ingest(
        user_id="house-a", observation_id=pregrant, source_id="camera-1",
        consent=consent, now=now,
    )
    expiry = store.grant_instance_identity_consent(
        user_id="house-a", source_id="camera-1", ttl_seconds=300,
    )
    assert expiry > now
    assert not service.ingest(
        user_id="house-a", observation_id=pregrant, source_id="camera-1",
        consent=consent, now=now,
    )

    # Only newly captured post-grant frames may acquire synthetic identity links.
    base = datetime.now(timezone.utc)
    first = _sighting(
        store, suffix="a-first", location="living-room", observed_at=base,
    )
    second = _sighting(
        store, suffix="a-second", location="kitchen",
        observed_at=base + timedelta(seconds=1),
    )
    other_keys = _sighting(
        store, suffix="b-first", location="living-room",
        observed_at=base + timedelta(seconds=1),
    )
    for observation_id, instance_id, proof_id in (
        (first, "keys-a", "synthetic-proof-a-first"),
        (second, "keys-a", "synthetic-proof-a-second"),
        (other_keys, "keys-b", "synthetic-proof-b-first"),
    ):
        proofs[("house-a", observation_id, "camera-1")] = VerifiedInstanceProof(
            user_id="house-a", observation_id=observation_id, source_id="camera-1",
            instance_id=instance_id, identity_evidence_id=proof_id,
            identity_confidence=0.98,
        )
    for observation_id in (first, second, other_keys):
        assert service.ingest(
            user_id="house-a", observation_id=observation_id, source_id="camera-1",
            consent=consent, now=now,
        )

    query = HomeAgentQueryService(store)
    changes = query.observed_location_changes(
        user_id="house-a", object_name="keys",
    )
    assert len(changes) == 1
    change = changes[0]
    assert (change.instance_id, change.from_location, change.to_location) == (
        "keys-a", "living-room", "kitchen",
    )
    assert (change.from_evidence_id, change.to_evidence_id) == (first, second)
    assert query.observed_location_changes(
        user_id="house-b", object_name="keys",
    ) == []

    # Revocation removes all three identity links, but preserves all four class sightings.
    assert store.revoke_instance_identity_consent(
        user_id="house-a", source_id="camera-1",
    ) == 3
    assert query.observed_location_changes(
        user_id="house-a", object_name="keys",
    ) == []
    assert len(store.history(user_id="house-a", object_name="keys")) == 4
