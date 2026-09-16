from datetime import datetime, timedelta, timezone

import pytest

from app.services.home_agent.authenticated_image_ingest import AuthenticatedHomeImageIngest
from app.services.home_agent.capture_registry import CaptureSessionRegistry
from app.services.home_agent.capture_session import CaptureSession


NOW = datetime(2026, 9, 16, 19, 0, tzinfo=timezone.utc)


class RecordingImageIngest:
    def __init__(self):
        self.calls = []

    def ingest(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["consent"].allows(
            user_id=kwargs["user_id"], source_id=kwargs["source_id"], now=kwargs["now"]
        )
        return {"stored": True, "frame_id": "frame-1"}


def _service():
    registry = CaptureSessionRegistry()
    session = CaptureSession(
        session_id="capture-1",
        user_id="user-a",
        source_id="camera-entry",
        started_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    registry.register(session)
    image_ingest = RecordingImageIngest()
    return AuthenticatedHomeImageIngest(registry=registry, image_ingest=image_ingest), image_ingest


def test_active_authenticated_session_derives_consent_for_image_ingest():
    service, image_ingest = _service()
    result = service.ingest(
        session_id="capture-1",
        user_id="user-a",
        source_id="camera-entry",
        image_bytes=b"image-bytes",
        location="entry table",
        observed_at=NOW,
        now=NOW + timedelta(seconds=10),
    )

    assert result == {"stored": True, "frame_id": "frame-1"}
    assert len(image_ingest.calls) == 1
    call = image_ingest.calls[0]
    assert call["user_id"] == "user-a"
    assert call["source_id"] == "camera-entry"
    assert call["location"] == "entry table"


@pytest.mark.parametrize(
    ("user_id", "source_id", "now"),
    [
        ("user-b", "camera-entry", NOW + timedelta(seconds=10)),
        ("user-a", "camera-office", NOW + timedelta(seconds=10)),
        ("user-a", "camera-entry", NOW + timedelta(minutes=5)),
    ],
)
def test_image_bytes_never_reach_detector_for_mismatched_or_expired_session(user_id, source_id, now):
    service, image_ingest = _service()

    with pytest.raises(PermissionError, match="capture session"):
        service.ingest(
            session_id="capture-1",
            user_id=user_id,
            source_id=source_id,
            image_bytes=b"private-image",
            location="entry table",
            observed_at=NOW,
            now=now,
        )

    assert image_ingest.calls == []
