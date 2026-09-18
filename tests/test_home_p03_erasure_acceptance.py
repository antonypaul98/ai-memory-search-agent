"""Real-Postgres acceptance for Home capture fencing and physical-memory erasure."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.postgres_capture_store import PostgresCaptureStore
from app.db.postgres_home_image_store import PostgresHomeImageStore
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.services import privacy_erasure
from app.services.home_agent.capture_registry import CaptureSessionRegistry
from app.services.home_agent.capture_session import CaptureSession
from app.services.home_agent.image_ingest import DetectedObject, ImageObservationBatch


class _EmptyPrivacyService:
    def delete_all_memories(self, *, user_id: str):
        return {"deleted_count": 0, "errors": []}


def _session(*, session_id: str, user_id: str, source_id: str, now: datetime) -> CaptureSession:
    return CaptureSession(
        session_id=session_id,
        user_id=user_id,
        source_id=source_id,
        started_at=now,
        expires_at=now + timedelta(minutes=5),
    )


def _seed_home_image(store: PostgresHomeImageStore, *, user_id: str, nonce: str, now: datetime) -> None:
    image_bytes = f"private-home-frame-{user_id}".encode()
    from hashlib import sha256
    batch = ImageObservationBatch(
        user_id=user_id,
        frame_id=f"frame-{user_id}-{nonce}",
        image_bytes=image_bytes,
        image_sha256=sha256(image_bytes).hexdigest(),
        source_id=f"camera-{user_id}",
        location="test-room",
        observed_at=now,
        detector_id="p03-acceptance",
        detections=(DetectedObject(object_class="test-object", confidence=0.99, box=(0.1, 0.2, 0.3, 0.4)),),
    )
    result = store.store_image_batch(batch)
    assert result["stored_observations"] == 1


def test_real_postgres_home_erasure_fences_owner_and_preserves_neighbor(monkeypatch, tmp_path):
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
    capture_store = PostgresCaptureStore(factory)
    home_store = PostgresHomeImageStore(factory)
    nonce = uuid4().hex
    owner = f"home-erasure-owner-{nonce}"
    other = f"home-erasure-other-{nonce}"
    owner_capture = f"owner-capture-{nonce}"
    other_capture = f"other-capture-{nonce}"
    now = datetime.now(timezone.utc)

    monkeypatch.setattr(privacy_erasure, "delete_user_feedback_data", lambda factory, *, user_id: {})
    monkeypatch.setattr(privacy_erasure, "PostgresModelUsageLedger", lambda factory: SimpleNamespace(delete_user_data=lambda *, user_id: 0))
    monkeypatch.setattr(privacy_erasure, "PostgresEventStore", lambda factory: SimpleNamespace(delete_user_data=lambda *, user_id: {}))
    monkeypatch.setattr(privacy_erasure, "delete_user_graph", lambda settings, *, user_id: {})
    monkeypatch.setattr(privacy_erasure, "delete_user_intelligence", lambda factory, *, user_id: {})

    registry = CaptureSessionRegistry()
    owner_session = _session(session_id=f"owner-session-{nonce}", user_id=owner, source_id="camera-owner", now=now)
    other_session = _session(session_id=f"other-session-{nonce}", user_id=other, source_id="camera-other", now=now)
    registry.register(owner_session)
    registry.register(other_session)

    capture_store.create(capture_id=owner_capture, user_id=owner, url="home://owner", url_hash=f"owner-{nonce}", title="owner", source_type="home", payload_json='{"private":"owner"}', now=now.isoformat())
    capture_store.create(capture_id=other_capture, user_id=other, url="home://other", url_hash=f"other-{nonce}", title="other", source_type="home", payload_json='{"private":"other"}', now=now.isoformat())
    _seed_home_image(home_store, user_id=owner, nonce=nonce, now=now)
    _seed_home_image(home_store, user_id=other, nonce=nonce, now=now)

    home_tables = ("home_image_observations", "home_image_evidence", "home_physical_objects", "home_object_sightings")
    try:
        result = privacy_erasure.delete_production_user_data(settings, user_id=owner, privacy_service=_EmptyPrivacyService(), capture_registry=registry)
        assert result["deleted"] is True
        assert result["capture_sessions_revoked"] == 1
        assert result["capture_payloads_deleted"] == 1
        assert result["home_physical_deleted"] == {"image_observations": 1, "image_evidence": 1, "physical_objects": 1, "sightings": 1}
        assert capture_store.list_for_user(user_id=owner) == []
        assert [row["capture_id"] for row in capture_store.list_for_user(user_id=other)] == [other_capture]

        with pytest.raises(PermissionError, match="missing, mismatched, or expired"):
            registry.resolve(session_id=owner_session.session_id, user_id=owner, source_id=owner_session.source_id, now=now)
        assert registry.resolve(session_id=other_session.session_id, user_id=other, source_id=other_session.source_id, now=now) == other_session

        with factory() as conn:
            for table in home_tables:
                assert conn.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE user_id = %s", (owner,)).fetchone()["count"] == 0
                assert conn.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE user_id = %s", (other,)).fetchone()["count"] == 1
    finally:
        capture_store.delete_for_user(user_id=owner)
        capture_store.delete_for_user(user_id=other)
        with factory() as conn:
            for table in home_tables:
                conn.execute(f"DELETE FROM {table} WHERE user_id IN (%s, %s)", (owner, other))
