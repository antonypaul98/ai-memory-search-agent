"""Synthetic camera-to-retained-frame bridge tests; no hardware/identity proof."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.home_agent.capture_registry import CaptureSessionRegistry
from app.services.home_agent.capture_session import CaptureSession
from app.services.home_agent.image_capture_bridge import ImageCaptureBridge

NOW = datetime(2026, 10, 27, 18, tzinfo=timezone.utc)


class FakeDevice:
    def __init__(self, frames=(b"frame-1", b"frame-2", b"frame-3")):
        self.frames = list(frames)
        self.opened = False
        self.closed = False
        self.reads = 0

    def open(self):
        self.opened = True

    def read(self):
        self.reads += 1
        return self.frames.pop(0) if self.frames else None

    def close(self):
        self.closed = True


class FakeIngest:
    def __init__(self, *, on_ingest=None, stored=True):
        self.calls = []
        self.on_ingest = on_ingest
        self.stored = stored

    def ingest(self, **kwargs):
        self.calls.append(kwargs)
        if self.on_ingest:
            self.on_ingest()
        return {"stored": self.stored, "frame_id": f"frame-{len(self.calls)}"}


def setup(*, user_id="tenant-a", source_id="camera-1", clock=None, ingest=None):
    registry = CaptureSessionRegistry()
    session = CaptureSession(
        session_id="opaque-session", user_id=user_id, source_id=source_id,
        started_at=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=1),
    )
    registry.register(session)
    ingest = ingest or FakeIngest()
    bridge = ImageCaptureBridge(registry=registry, image_ingest=ingest,
                                clock=clock or (lambda: NOW), sleeper=lambda _: None)
    return bridge, registry, ingest


def run(bridge, device, **kwargs):
    arguments = dict(device=device, session_id="opaque-session", user_id="tenant-a",
                     source_id="camera-1", location="office", max_frames=2)
    arguments.update(kwargs)
    return bridge.run_device(**arguments)


def test_two_raw_frames_reach_existing_authenticated_image_ingest_and_camera_closes():
    bridge, _, ingest = setup()
    device = FakeDevice()
    result = run(bridge, device)
    assert result.frames_processed == 2
    assert result.frames_stored == 2
    assert result.frame_ids == ("frame-1", "frame-2")
    assert result.source_closed and device.closed and device.reads == 2
    assert [call["image_bytes"] for call in ingest.calls] == [b"frame-1", b"frame-2"]
    assert all(call["user_id"] == "tenant-a" and call["source_id"] == "camera-1"
               and call["location"] == "office" and call["now"] == NOW
               for call in ingest.calls)


def test_mismatched_tenant_or_source_cannot_open_camera():
    bridge, _, ingest = setup()
    for change in ({"user_id": "tenant-b"}, {"source_id": "camera-2"},
                   {"session_id": "not-a-session"}):
        device = FakeDevice()
        with pytest.raises(PermissionError):
            run(bridge, device, **change)
        assert not device.opened and not device.closed
    assert ingest.calls == []


def test_revocation_between_frames_stops_and_closes_camera():
    registry = CaptureSessionRegistry()
    session = CaptureSession("opaque-session", "tenant-a", "camera-1",
                             NOW - timedelta(minutes=1), NOW + timedelta(minutes=1))
    registry.register(session)
    ingest = FakeIngest(on_ingest=lambda: registry.revoke(session_id="opaque-session"))
    bridge = ImageCaptureBridge(registry=registry, image_ingest=ingest,
                                clock=lambda: NOW, sleeper=lambda _: None)
    device = FakeDevice()
    with pytest.raises(PermissionError):
        run(bridge, device)
    assert len(ingest.calls) == 1 and device.closed


def test_expired_session_cannot_open_camera():
    bridge, _, ingest = setup(clock=lambda: NOW + timedelta(minutes=2))
    device = FakeDevice()
    with pytest.raises(PermissionError):
        run(bridge, device)
    assert not device.opened and ingest.calls == []


def test_frame_predating_session_cannot_be_persisted():
    instants = iter((NOW, NOW - timedelta(minutes=2), NOW))
    bridge, _, ingest = setup(clock=lambda: next(instants))
    device = FakeDevice()
    with pytest.raises(PermissionError):
        run(bridge, device, max_frames=1)
    assert device.closed and ingest.calls == []


def test_ingest_failure_still_releases_camera():
    def fail():
        raise ValueError("simulated persistence failure")
    bridge, _, ingest = setup(ingest=FakeIngest(on_ingest=fail))
    device = FakeDevice()
    with pytest.raises(ValueError, match="simulated persistence failure"):
        run(bridge, device)
    assert device.closed and len(ingest.calls) == 1


def test_no_frame_is_not_claimed_as_stored():
    bridge, _, ingest = setup()
    result = run(bridge, FakeDevice(frames=()))
    assert result.frames_processed == result.frames_stored == 0
    assert result.frame_ids == () and result.source_closed
    assert ingest.calls == []


def test_false_store_result_is_not_counted_as_persisted():
    bridge, _, _ = setup(ingest=FakeIngest(stored=False))
    result = run(bridge, FakeDevice(), max_frames=1)
    assert result.frames_processed == 1 and result.frames_stored == 0
    assert result.frame_ids == ()


@pytest.mark.parametrize("invalid", [0, 31, -1, True, 1.5])
def test_invalid_frame_limit_rejected_before_camera_open(invalid):
    bridge, _, _ = setup()
    device = FakeDevice()
    with pytest.raises(ValueError):
        run(bridge, device, max_frames=invalid)
    assert not device.opened


def test_run_camera_uses_injected_factory_without_real_hardware():
    bridge, _, _ = setup()
    device = FakeDevice()
    seen = []
    def factory(*, device_index):
        seen.append(device_index)
        return device
    result = bridge.run_camera(device_index=2, device_factory=factory,
                               session_id="opaque-session", user_id="tenant-a",
                               source_id="camera-1", location="office", max_frames=1)
    assert seen == [2] and result.frames_stored == 1 and device.closed


def test_no_identity_verifier_is_invoked_by_bridge():
    bridge, _, ingest = setup()
    result = run(bridge, FakeDevice(), max_frames=1)
    assert result.frames_stored == 1
    assert not hasattr(bridge, "_verifier")
    assert not any("instance_id" in call or "identity_evidence_id" in call
                   for call in ingest.calls)


def test_real_image_ingest_contract_retains_evidence_without_identity_proof():
    from io import BytesIO
    from PIL import Image
    from app.services.home_agent.authenticated_image_ingest import AuthenticatedHomeImageIngest
    from app.services.home_agent.image_ingest import HomeImageIngestService, DetectedObject

    encoded = BytesIO()
    Image.new("RGB", (80, 80), (20, 30, 40)).save(encoded, format="PNG")
    class Detector:
        detector_id = "synthetic-test-detector"
        def detect(self, image):
            return [DetectedObject("keys", 0.96, (0.1, 0.1, 0.8, 0.8))]
    class Store:
        def __init__(self): self.batches = []
        def store_image_batch(self, batch):
            self.batches.append(batch)
            return {"stored": True, "frame_id": batch.frame_id}
    registry = CaptureSessionRegistry()
    registry.register(CaptureSession("opaque-session", "tenant-a", "camera-1",
                                     NOW - timedelta(minutes=1), NOW + timedelta(minutes=1)))
    store = Store()
    image_ingest = AuthenticatedHomeImageIngest(
        registry=registry, image_ingest=HomeImageIngestService(store, Detector()),
    )
    bridge = ImageCaptureBridge(registry=registry, image_ingest=image_ingest,
                                clock=lambda: NOW, sleeper=lambda _: None)
    result = run(bridge, FakeDevice(frames=(encoded.getvalue(),)), max_frames=1)
    assert result.frames_processed == result.frames_stored == 1
    assert result.source_closed and result.frame_ids == (store.batches[0].frame_id,)
    assert store.batches[0].user_id == "tenant-a"
    assert store.batches[0].source_id == "camera-1"
    assert store.batches[0].location == "office"
    assert store.batches[0].detections[0].object_class == "keys"
    assert not hasattr(store.batches[0], "instance_id")


class ResultIngest:
    """Use exact legacy and PostgreSQL persistence response shapes."""

    def __init__(self, responses):
        self.responses = iter(responses)

    def ingest(self, **kwargs):
        return next(self.responses)


@pytest.mark.parametrize("response,expected_id", [
    ({"stored": True, "frame_id": "legacy"}, "legacy"),
    ({"stored": False, "frame_id": "legacy"}, None),
    ({"frame_id": None, "stored_observations": 0, "retained_bytes": 0}, None),
    ({"frame_id": "duplicate", "stored_observations": 0, "retained_bytes": 0}, None),
    ({"frame_id": "fresh", "stored_observations": 2, "retained_bytes": 100}, "fresh"),
    ({"frame_id": "fresh", "stored_observations": 2, "retained_bytes": 100,
      "stored": True}, "fresh"),
])
def test_postgres_style_retention_accounting(response, expected_id):
    bridge, _, _ = setup(ingest=ResultIngest([response]))
    device = FakeDevice()
    result = run(bridge, device, max_frames=1)
    assert result.frames_processed == 1
    assert result.frames_stored == (1 if expected_id else 0)
    assert result.frame_ids == ((expected_id,) if expected_id else ())
    assert result.source_closed and device.closed


@pytest.mark.parametrize("response", [
    None, {}, [], {"frame_id": "missing-status"},
    {"stored": None, "frame_id": "a"},
    {"stored": 1, "frame_id": "a"},
    {"stored": True, "frame_id": ""},
    {"stored": True, "frame_id": None},
    {"frame_id": "a", "stored_observations": 1},
    {"frame_id": "a", "retained_bytes": 1},
    {"frame_id": "a", "stored_observations": 0, "retained_bytes": 1},
    {"frame_id": "a", "stored_observations": 1, "retained_bytes": 0},
    {"frame_id": "a", "stored_observations": True, "retained_bytes": 1},
    {"frame_id": "a", "stored_observations": 1, "retained_bytes": False},
    {"frame_id": "a", "stored_observations": -1, "retained_bytes": 1},
    {"frame_id": "a", "stored_observations": 1, "retained_bytes": -1},
    {"frame_id": "a", "stored_observations": 1.5, "retained_bytes": 1},
    {"frame_id": "a", "stored_observations": 1, "retained_bytes": 1.5},
    {"frame_id": None, "stored_observations": 1, "retained_bytes": 1},
    {"frame_id": "  ", "stored_observations": 1, "retained_bytes": 1},
    {"frame_id": "a", "stored_observations": 1, "retained_bytes": 1,
     "stored": False},
    {"frame_id": "a", "stored_observations": 0, "retained_bytes": 0,
     "stored": True},
    {"frame_id": "a", "stored_observations": 1, "retained_bytes": 1,
     "stored": 1},
])
def test_malformed_retention_response_fails_closed_and_releases_camera(response):
    bridge, _, _ = setup(ingest=ResultIngest([response]))
    device = FakeDevice()
    with pytest.raises(ValueError):
        run(bridge, device, max_frames=1)
    assert device.closed


def test_authenticated_still_image_session_observation_window():
    """Direct still-image API ingestion must enforce the same session window as the camera bridge."""
    from app.services.home_agent.authenticated_image_ingest import AuthenticatedHomeImageIngest

    class RecordingImageIngest:
        def __init__(self):
            self.calls = []

        def ingest(self, **kwargs):
            self.calls.append(kwargs)
            return {"stored": False}

    _, registry, _ = setup()
    downstream = RecordingImageIngest()
    service = AuthenticatedHomeImageIngest(registry=registry, image_ingest=downstream)
    kwargs = dict(
        session_id="opaque-session", user_id="tenant-a", source_id="camera-1",
        image_bytes=b"synthetic-image", location="office", now=NOW,
    )
    for invalid in (NOW - timedelta(minutes=2), NOW + timedelta(minutes=2)):
        with pytest.raises(PermissionError, match="outside the active capture session"):
            service.ingest(observed_at=invalid, **kwargs)
    assert downstream.calls == []
    assert service.ingest(observed_at=NOW - timedelta(seconds=30), **kwargs) == {"stored": False}
    assert len(downstream.calls) == 1
    assert downstream.calls[0]["observed_at"] == NOW - timedelta(seconds=30)


def test_authenticated_still_image_rejects_naive_observation_time_before_downstream():
    from app.services.home_agent.authenticated_image_ingest import AuthenticatedHomeImageIngest

    class NoCalls:
        def ingest(self, **kwargs):
            raise AssertionError("must not reach image detector/store")

    _, registry, _ = setup()
    service = AuthenticatedHomeImageIngest(registry=registry, image_ingest=NoCalls())
    with pytest.raises(ValueError, match="observed_at must be timezone-aware"):
        service.ingest(
            session_id="opaque-session", user_id="tenant-a", source_id="camera-1",
            image_bytes=b"synthetic-image", location="office",
            observed_at=NOW.replace(tzinfo=None), now=NOW,
        )
