"""Real PostgreSQL acceptance of opt-in camera-to-image memory, without hardware.

Requires MEMORY_AGENT_TEST_POSTGRES_DSN. These are synthetic PNG frames and a
fixture detector; successful persistence is not proof of physical object identity.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
import os
from uuid import uuid4

import pytest
from PIL import Image

from app.config import Settings
from app.db.postgres_home_image_store import PostgresHomeImageStore
from app.db.postgres_runtime import get_postgres_connection_factory
from app.services.home_agent.authenticated_image_ingest import AuthenticatedHomeImageIngest
from app.services.home_agent.capture_registry import CaptureSessionRegistry
from app.services.home_agent.capture_session import CaptureSession
from app.services.home_agent.image_capture_bridge import ImageCaptureBridge
from app.services.home_agent.image_ingest import DetectedObject, HomeImageIngestService


@pytest.fixture
def isolated_postgres(monkeypatch):
    dsn = os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("real PostgreSQL DSN required")
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    schema = "home_camera_" + uuid4().hex
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    alias = "HOME_CAMERA_DSN_" + uuid4().hex
    monkeypatch.setenv(alias, make_conninfo(dsn, options=f"-c search_path={schema}"))
    factory = get_postgres_connection_factory(
        Settings(_env_file=None, postgres_dsn_env=alias)
    )
    try:
        yield PostgresHomeImageStore(factory), factory
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                sql.Identifier(schema)
            ))


class SyntheticCamera:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.closed = False
        self.reads = 0

    def open(self):
        pass

    def read(self):
        self.reads += 1
        return next(self.frames, None)

    def close(self):
        self.closed = True


class FixtureDetector:
    detector_id = "synthetic-postgres-camera-test"

    def __init__(self, detections):
        self._detections = detections

    def detect(self, image):
        return self._detections


def _png():
    output = BytesIO()
    Image.new("RGB", (32, 32), (20, 30, 40)).save(output, format="PNG")
    return output.getvalue()


def _bridge(store, detector, now):
    registry = CaptureSessionRegistry()
    registry.register(CaptureSession(
        session_id="synthetic-session", user_id="house-a", source_id="camera-a",
        started_at=now - timedelta(seconds=5),
        expires_at=now + timedelta(minutes=2),
    ))
    ingest = AuthenticatedHomeImageIngest(
        registry=registry, image_ingest=HomeImageIngestService(store, detector),
    )
    return ImageCaptureBridge(
        registry=registry, image_ingest=ingest,
        clock=lambda: now, sleeper=lambda _: None,
    )


def _capture(bridge, device, *, max_frames):
    return bridge.run_device(
        device=device, session_id="synthetic-session", user_id="house-a",
        source_id="camera-a", location="office", max_frames=max_frames,
    )


def _count(factory, table):
    with factory() as conn:
        return conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE user_id=%s", ("house-a",)
        ).fetchone()["n"]


def test_real_postgres_retention_duplicate_and_erasure(isolated_postgres):
    store, factory = isolated_postgres
    now = datetime.now(timezone.utc)
    detector = FixtureDetector([DetectedObject("keys", 0.96, (0.1, 0.1, 0.8, 0.8))])
    bridge = _bridge(store, detector, now)
    frame = _png()
    camera = SyntheticCamera([frame, frame])

    result = _capture(bridge, camera, max_frames=2)
    assert result.frames_processed == 2
    assert result.frames_stored == 1  # Same bytes and timestamp: idempotent retry.
    assert len(result.frame_ids) == 1
    assert result.source_closed and camera.closed and camera.reads == 2
    frame_id = result.frame_ids[0]
    assert store.get_image(user_id="house-a", frame_id=frame_id) is not None
    assert _count(factory, "home_image_evidence") == 1
    assert _count(factory, "home_image_observations") == 1
    assert _count(factory, "home_verified_instance_associations") == 0

    assert store.delete_image(user_id="house-a", frame_id=frame_id)
    assert store.get_image(user_id="house-a", frame_id=frame_id) is None
    assert _count(factory, "home_image_evidence") == 0
    assert _count(factory, "home_image_observations") == 0
    assert _count(factory, "home_object_sightings") == 0


def test_real_postgres_empty_detections_do_not_retain_frame(isolated_postgres):
    store, factory = isolated_postgres
    bridge = _bridge(store, FixtureDetector([]), datetime.now(timezone.utc))
    camera = SyntheticCamera([_png()])
    result = _capture(bridge, camera, max_frames=1)
    assert result.frames_processed == 1 and result.frames_stored == 0
    assert result.frame_ids == () and result.source_closed and camera.closed
    assert _count(factory, "home_image_evidence") == 0
    assert _count(factory, "home_image_observations") == 0
