from datetime import datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import Mock

import pytest
from PIL import Image

from app.services.home_agent.authenticated_image_capture import AuthenticatedImageCapture
from app.services.home_agent.capture_registry import CaptureSessionRegistry
from app.services.home_agent.capture_session import CaptureSession
from app.services.home_agent.image_ingest import DetectedObject

NOW = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)


def png_bytes():
    out = BytesIO(); Image.new("RGB", (8, 8)).save(out, format="PNG"); return out.getvalue()


class Detector:
    detector_id = "detector-1"
    def detect(self, image):
        return [DetectedObject("person", 0.95, (0.1, 0.1, 0.8, 0.9))]


class Store:
    def __init__(self): self.batches = []
    def store_image_batch(self, batch): self.batches.append(batch); return {"stored": True}


def registry(expires=NOW + timedelta(minutes=5)):
    value = CaptureSessionRegistry()
    value.register(CaptureSession(
        session_id="session-1", user_id="tenant-a", source_id="front-door-camera",
        started_at=NOW - timedelta(minutes=5), expires_at=expires,
    ))
    return value


def test_validated_image_batch_is_forwarded_with_authenticated_session():
    store = Store(); bridge = Mock(); bridge.ingest_batch.return_value = None
    service = AuthenticatedImageCapture(
        registry=registry(), image_store=store, detector=Detector(), presence_bridge=bridge,
    )
    result, event = service.ingest(
        session_id="session-1", user_id="tenant-a", source_id="front-door-camera",
        image_bytes=png_bytes(), location="entry", observed_at=NOW, now=NOW,
    )
    assert result["stored"] is True and event is None and len(store.batches) == 1
    call = bridge.ingest_batch.call_args.kwargs
    assert call["session_id"] == "session-1" and call["user_id"] == "tenant-a"
    assert call["batch"] is store.batches[0]
    assert call["batch"].detections[0].object_class == "person"


def test_wrong_tenant_fails_before_detection_or_storage():
    store = Store(); detector = Mock(); bridge = Mock()
    service = AuthenticatedImageCapture(
        registry=registry(), image_store=store, detector=detector, presence_bridge=bridge,
    )
    with pytest.raises(PermissionError):
        service.ingest(
            session_id="session-1", user_id="tenant-b", source_id="front-door-camera",
            image_bytes=png_bytes(), location="entry", observed_at=NOW, now=NOW,
        )
    detector.detect.assert_not_called(); assert store.batches == []; bridge.ingest_batch.assert_not_called()


def test_expired_session_fails_before_detection_or_storage():
    store = Store(); detector = Mock(); bridge = Mock()
    service = AuthenticatedImageCapture(
        registry=registry(expires=NOW - timedelta(minutes=1)), image_store=store,
        detector=detector, presence_bridge=bridge,
    )
    with pytest.raises(PermissionError):
        service.ingest(
            session_id="session-1", user_id="tenant-a", source_id="front-door-camera",
            image_bytes=png_bytes(), location="entry", observed_at=NOW - timedelta(minutes=2), now=NOW,
        )
    detector.detect.assert_not_called(); assert store.batches == []; bridge.ingest_batch.assert_not_called()
