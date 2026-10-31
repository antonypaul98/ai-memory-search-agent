"""Real PostgreSQL consent/revocation acceptance; synthetic sightings only.

Requires MEMORY_AGENT_TEST_POSTGRES_DSN. No camera or identity model is used:
VerifiedInstanceProof objects here are controlled fixtures, not real proof.
"""
from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.postgres_home_image_store import PostgresHomeImageStore
from app.db.postgres_runtime import get_postgres_connection_factory
from app.services.home_agent.image_ingest import (
    DetectedObject, ImageObservationBatch, canonical_id,
)
from app.services.home_agent.verified_identity_ingest import VerifiedInstanceProof


@pytest.fixture
def isolated_postgres(monkeypatch):
    base_dsn = os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN")
    if not base_dsn:
        pytest.skip("real PostgreSQL DSN required")

    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    schema = "home_consent_" + uuid4().hex
    with psycopg.connect(base_dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    alias = "HOME_CONSENT_DSN_" + uuid4().hex
    monkeypatch.setenv(alias, make_conninfo(base_dsn, options=f"-c search_path={schema}"))
    factory = get_postgres_connection_factory(
        Settings(_env_file=None, postgres_dsn_env=alias)
    )
    try:
        yield PostgresHomeImageStore(factory), factory
    finally:
        with psycopg.connect(base_dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                sql.Identifier(schema)
            ))


def _sighting(store, *, user_id: str, source_id: str, suffix: str,
              observed_at: datetime | None = None,
              image_suffix: str | None = None) -> str:
    # Use a post-grant capture time for positive consent tests.
    if observed_at is None:
        observed_at = datetime.now(timezone.utc)
    image_bytes = f"synthetic-frame:{user_id}:{source_id}:{image_suffix if image_suffix is not None else suffix}".encode()
    digest = hashlib.sha256(image_bytes).hexdigest()
    frame_id = canonical_id("frame", user_id, digest, source_id, "kitchen", suffix)
    detection = DetectedObject("keys", 0.96, (0.1, 0.2, 0.4, 0.6))
    batch = ImageObservationBatch(
        user_id=user_id, frame_id=frame_id, image_bytes=image_bytes,
        image_sha256=digest, source_id=source_id, location="kitchen",
        observed_at=observed_at, detector_id="synthetic-detector",
        detections=(detection,),
    )
    assert store.store_image_batch(batch)["stored_observations"] == 1
    return canonical_id(
        "observation", frame_id, detection.object_class, json.dumps(detection.box)
    )


def _proof(user_id: str, source_id: str, observation_id: str, suffix: str):
    return VerifiedInstanceProof(
        user_id=user_id, observation_id=observation_id, source_id=source_id,
        instance_id=f"keys-{user_id}", identity_evidence_id=f"fixture-proof-{suffix}",
        identity_confidence=0.97,
    )


def _count(factory, table: str, user_id: str) -> int:
    with factory() as conn:
        return conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE user_id=%s", (user_id,)
        ).fetchone()["n"]


def test_real_postgres_consent_revoke_expiry_and_tenant_isolation(isolated_postgres):
    store, factory = isolated_postgres
    pregrant = _sighting(store, user_id="house-a", source_id="camera-a", suffix="pregrant")
    # A client may supply a future observed_at before consent exists. The
    # server-retention time must still prevent retroactive identity linking.
    pregrant_future = _sighting(
        store, user_id="house-a", source_id="camera-a", suffix="pregrant-future",
        observed_at=datetime.now(timezone.utc) + timedelta(days=1),
    )

    # A proof without server consent cannot be stored.
    assert not store.store_verified_instance_association(
        proof=_proof("house-a", "camera-a", pregrant, "before-grant")
    )
    store.grant_instance_identity_consent(
        user_id="house-a", source_id="camera-a", ttl_seconds=300
    )
    store.grant_instance_identity_consent(
        user_id="house-b", source_id="camera-a", ttl_seconds=300
    )
    # Granting consent never authorizes retroactive identity linking.
    assert not store.store_verified_instance_association(
        proof=_proof("house-a", "camera-a", pregrant, "pregrant-replay")
    )
    assert not store.store_verified_instance_association(
        proof=_proof("house-a", "camera-a", pregrant_future, "future-timestamp-replay")
    )
    a = _sighting(store, user_id="house-a", source_id="camera-a", suffix="one")
    b = _sighting(store, user_id="house-b", source_id="camera-a", suffix="one")
    other_source = _sighting(
        store, user_id="house-a", source_id="camera-b", suffix="two"
    )
    assert not store.store_verified_instance_association(
        proof=_proof("house-a", "camera-a", b, "cross-tenant")
    )
    assert not store.store_verified_instance_association(
        proof=_proof("house-a", "camera-a", other_source, "wrong-source")
    )
    assert store.store_verified_instance_association(
        proof=_proof("house-a", "camera-a", a, "owner")
    )
    assert store.store_verified_instance_association(
        proof=_proof("house-b", "camera-a", b, "neighbor")
    )

    assert store.revoke_instance_identity_consent(
        user_id="house-a", source_id="camera-a"
    ) == 1
    assert store.revoke_instance_identity_consent(
        user_id="house-a", source_id="camera-a"
    ) == 0
    assert not store.store_verified_instance_association(
        proof=_proof("house-a", "camera-a", a, "after-revoke")
    )
    assert _count(factory, "home_verified_instance_associations", "house-a") == 0
    assert _count(factory, "home_verified_instance_associations", "house-b") == 1
    assert _count(factory, "home_object_sightings", "house-a") == 4

    # Regrant cannot relink previously captured frames; only new sightings qualify.
    store.grant_instance_identity_consent(
        user_id="house-a", source_id="camera-a", ttl_seconds=300
    )
    assert _count(factory, "home_verified_instance_associations", "house-a") == 0
    assert not store.store_verified_instance_association(
        proof=_proof("house-a", "camera-a", a, "after-regrant-old")
    )
    after_regrant = _sighting(
        store, user_id="house-a", source_id="camera-a", suffix="after-regrant"
    )
    assert store.store_verified_instance_association(
        proof=_proof("house-a", "camera-a", after_regrant, "after-regrant-new")
    )

    # Database time, not the caller's timestamp, governs expiry.
    store.grant_instance_identity_consent(
        user_id="house-a", source_id="camera-b", ttl_seconds=300
    )
    with factory() as conn:
        conn.execute("""
            UPDATE home_instance_identity_consents
            SET granted_at=CURRENT_TIMESTAMP - INTERVAL '2 seconds',
                expires_at=CURRENT_TIMESTAMP - INTERVAL '1 second'
            WHERE user_id=%s AND source_id=%s
        """, ("house-a", "camera-b"))
    assert not store.store_verified_instance_association(
        proof=_proof("house-a", "camera-b", other_source, "expired")
    )
    assert _count(factory, "home_verified_instance_associations", "house-a") == 1


def test_exact_image_replay_cannot_mint_fresh_identity_sighting(isolated_postgres):
    """Same bytes with a new frame ID/time cannot establish a new identity event.

    This is a synthetic exact-byte replay regression, not camera authenticity.
    """
    store, _ = isolated_postgres
    tenant, source = "house-replay", "camera-a"
    # The original frame was retained before identity consent.
    _sighting(store, user_id=tenant, source_id=source,
              suffix="old-frame", image_suffix="same-photo")
    store.grant_instance_identity_consent(
        user_id=tenant, source_id=source, ttl_seconds=300
    )
    # Re-submit identical bytes with a new frame ID and fresh observed_at.
    replay = _sighting(store, user_id=tenant, source_id=source,
                       suffix="new-timestamp", image_suffix="same-photo")
    assert not store.store_verified_instance_association(
        proof=_proof(tenant, source, replay, "replayed-old-photo")
    )

    fresh = _sighting(store, user_id=tenant, source_id=source,
                      suffix="genuine-new-bytes", image_suffix="new-photo")
    assert store.store_verified_instance_association(
        proof=_proof(tenant, source, fresh, "fresh")
    )
    duplicate = _sighting(store, user_id=tenant, source_id=source,
                          suffix="new-photo-again", image_suffix="new-photo")
    assert not store.store_verified_instance_association(
        proof=_proof(tenant, source, duplicate, "duplicate-fresh")
    )


def test_real_postgres_revoke_blocks_concurrent_writer(isolated_postgres):
    store, factory = isolated_postgres
    store.grant_instance_identity_consent(
        user_id="house-race", source_id="camera-a", ttl_seconds=300
    )
    observation = _sighting(
        store, user_id="house-race", source_id="camera-a", suffix="race"
    )
    proof = _proof("house-race", "camera-a", observation, "racing-write")

    # Hold the same consent row the writer must read FOR SHARE. Commit a
    # revocation before releasing the lock. A waiting writer must recheck the
    # revoked row under READ COMMITTED and must not persist an association.
    with factory() as blocker:
        blocker.execute("""
            SELECT 1 FROM home_instance_identity_consents
            WHERE user_id=%s AND source_id=%s FOR UPDATE
        """, ("house-race", "camera-a")).fetchone()
        started = Event()

        def write():
            started.set()
            return store.store_verified_instance_association(proof=proof)

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(write)
            try:
                assert started.wait(timeout=5)
                blocker.execute("""
                    UPDATE home_instance_identity_consents
                    SET revoked_at=CURRENT_TIMESTAMP
                    WHERE user_id=%s AND source_id=%s
                """, ("house-race", "camera-a"))
                blocker.commit()
                assert future.result(timeout=15) is False
            finally:
                # Never strand a blocked test worker on an open row lock.
                blocker.rollback()

    assert _count(factory, "home_verified_instance_associations", "house-race") == 0
    assert _count(factory, "home_object_sightings", "house-race") == 1
