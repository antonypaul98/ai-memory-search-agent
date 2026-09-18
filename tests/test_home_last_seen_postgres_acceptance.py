"""Real-Postgres acceptance for Home last-seen retrieval and evidence provenance."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.postgres_home_image_store import PostgresHomeImageStore
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.services.home_agent.image_ingest import DetectedObject, ImageObservationBatch
from app.services.home_agent.query_service import HomeAgentQueryService


def _batch(*, user_id: str, frame_id: str, location: str, observed_at: datetime,
           confidence: float, image_bytes: bytes) -> ImageObservationBatch:
    return ImageObservationBatch(
        user_id=user_id,
        frame_id=frame_id,
        image_bytes=image_bytes,
        image_sha256=sha256(image_bytes).hexdigest(),
        source_id=f"camera-{user_id}",
        location=location,
        observed_at=observed_at,
        detector_id="last-seen-acceptance",
        detections=(DetectedObject(
            object_class="keys",
            confidence=confidence,
            box=(0.1, 0.2, 0.4, 0.6),
        ),),
    )


def test_real_postgres_last_seen_is_tenant_scoped_and_evidence_backed(tmp_path):
    if not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"):
        pytest.skip("real Postgres DSN required")

    settings = Settings(
        _env_file=None,
        **{field: "postgres" for field in RELATIONAL_STORE_BACKEND_FIELDS},
        postgres_dsn_env="MEMORY_AGENT_TEST_POSTGRES_DSN",
        sqlite_path=str(tmp_path / "forbidden.db"),
        jobs_enabled=False,
    )
    factory = get_postgres_connection_factory(settings)
    store = PostgresHomeImageStore(factory)
    query = HomeAgentQueryService(store)
    nonce = uuid4().hex
    owner = f"home-last-seen-owner-{nonce}"
    other = f"home-last-seen-other-{nonce}"
    now = datetime.now(timezone.utc)
    owner_old = f"owner-old-{nonce}"
    owner_new = f"owner-new-{nonce}"
    other_frame = f"other-newest-{nonce}"
    owner_new_bytes = f"owner-new-evidence-{nonce}".encode()
    other_bytes = f"other-private-evidence-{nonce}".encode()

    try:
        assert store.store_image_batch(_batch(
            user_id=owner, frame_id=owner_old, location="kitchen-counter",
            observed_at=now - timedelta(minutes=10), confidence=0.91,
            image_bytes=f"owner-old-evidence-{nonce}".encode(),
        ))["stored_observations"] == 1
        assert store.store_image_batch(_batch(
            user_id=owner, frame_id=owner_new, location="entry-table",
            observed_at=now - timedelta(minutes=2), confidence=0.97,
            image_bytes=owner_new_bytes,
        ))["stored_observations"] == 1
        # This is globally newer, but belongs to a different tenant and must never win.
        assert store.store_image_batch(_batch(
            user_id=other, frame_id=other_frame, location="private-bedroom",
            observed_at=now, confidence=0.99, image_bytes=other_bytes,
        ))["stored_observations"] == 1

        answer = query.where_is(user_id=owner, object_name="KEYS", min_confidence=0.5)
        assert answer is not None
        assert answer.location == "entry-table"
        assert answer.confidence == pytest.approx(0.97)
        assert answer.source_id == f"camera-{owner}"
        assert answer.evidence_frame_id == owner_new
        assert answer.evidence_image_sha256 == sha256(owner_new_bytes).hexdigest()
        assert answer.evidence_detector_id == "last-seen-acceptance"
        assert query.evidence_image(user_id=owner, answer=answer) == owner_new_bytes

        # Even with a known foreign frame id, tenant scoping prevents evidence disclosure.
        assert query.evidence_frame(user_id=owner, frame_id=other_frame) is None
        other_answer = query.where_is(user_id=other, object_name="keys", min_confidence=0.5)
        assert other_answer is not None
        assert other_answer.location == "private-bedroom"
        assert query.evidence_image(user_id=other, answer=other_answer) == other_bytes
    finally:
        with factory() as conn:
            for user_id in (owner, other):
                conn.execute("DELETE FROM home_object_sightings WHERE user_id=%s", (user_id,))
                conn.execute("DELETE FROM home_image_evidence WHERE user_id=%s", (user_id,))
                conn.execute("DELETE FROM home_physical_objects WHERE user_id=%s", (user_id,))
