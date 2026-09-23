from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from app.services.home_agent.authenticated_image_presence import AuthenticatedImagePresenceBridge
from app.services.home_agent.image_ingest import DetectedObject, ImageObservationBatch

NOW = datetime(2026, 9, 23, 15, 0, tzinfo=timezone.utc)


def batch(*, user_id="tenant-a", source_id="front-door-camera"):
    return ImageObservationBatch(
        user_id=user_id,
        frame_id="frame-validated",
        image_bytes=b"cleaned-png",
        image_sha256="abc123",
        source_id=source_id,
        location="entry",
        observed_at=NOW,
        detector_id="detector-1",
        detections=(DetectedObject("person", 0.94, (0.1, 0.1, 0.5, 0.8)),),
    )


def test_validated_batch_preserves_frame_provenance_and_uses_authenticated_bridge():
    frame_bridge = Mock()
    frame_bridge.ingest_frames.return_value = None
    bridge = AuthenticatedImagePresenceBridge(frame_bridge=frame_bridge)

    assert bridge.ingest_batch(
        session_id="session-1", user_id="tenant-a", batch=batch(), now=NOW,
    ) is None

    call = frame_bridge.ingest_frames.call_args.kwargs
    assert call["session_id"] == "session-1"
    assert call["user_id"] == "tenant-a"
    assert call["source_id"] == "front-door-camera"
    detections, observed_at, evidence_id = call["frames"][0]
    assert detections[0].object_class == "person"
    assert observed_at == NOW
    assert evidence_id == "frame-validated"


def test_batch_tenant_mismatch_fails_before_authenticated_bridge():
    frame_bridge = Mock()
    bridge = AuthenticatedImagePresenceBridge(frame_bridge=frame_bridge)

    with pytest.raises(PermissionError):
        bridge.ingest_batch(
            session_id="session-1", user_id="tenant-b", batch=batch(user_id="tenant-a"), now=NOW,
        )

    frame_bridge.ingest_frames.assert_not_called()
