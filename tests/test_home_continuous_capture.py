from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app.services.home_agent.capture_registry import CaptureSessionRegistry
from app.services.home_agent.capture_session import CaptureSession
from app.services.home_agent.continuous_capture import CaptureFrame, ContinuousCaptureRunner

START = datetime(2026, 9, 23, 20, 0, tzinfo=timezone.utc)


def registry(expires=START + timedelta(seconds=10)):
    value = CaptureSessionRegistry()
    value.register(CaptureSession(
        session_id="session-1", user_id="tenant-a", source_id="camera-1",
        started_at=START, expires_at=expires,
    ))
    return value


def frame(offset):
    return CaptureFrame(b"image", START + timedelta(seconds=offset))


def test_runner_processes_bounded_frames_through_authenticated_capture():
    capture = Mock(); capture.ingest.return_value = ({"stored": True}, None)
    runner = ContinuousCaptureRunner(registry=registry(), capture=capture)
    result = runner.run(
        session_id="session-1", user_id="tenant-a", source_id="camera-1",
        location="entry", frames=[frame(0), frame(1), frame(2)], max_frames=2,
    )
    assert result.frames_processed == 2
    assert result.stopped_reason == "frame_limit"
    assert capture.ingest.call_count == 2


def test_runner_stops_before_frame_when_session_expires():
    capture = Mock(); capture.ingest.return_value = ({"stored": True}, None)
    runner = ContinuousCaptureRunner(registry=registry(expires=START + timedelta(seconds=2)), capture=capture)
    result = runner.run(
        session_id="session-1", user_id="tenant-a", source_id="camera-1",
        location="entry", frames=[frame(0), frame(1), frame(2)],
    )
    assert result.frames_processed == 2
    assert result.stopped_reason == "session_inactive"
    assert capture.ingest.call_count == 2


def test_revoked_session_stops_without_capture():
    reg = registry(); reg.revoke(session_id="session-1")
    capture = Mock(); runner = ContinuousCaptureRunner(registry=reg, capture=capture)
    result = runner.run(
        session_id="session-1", user_id="tenant-a", source_id="camera-1",
        location="entry", frames=[frame(0)],
    )
    assert result.frames_processed == 0
    assert result.stopped_reason == "session_inactive"
    capture.ingest.assert_not_called()


def test_runner_rejects_frames_faster_than_bounded_cadence():
    capture = Mock(); capture.ingest.return_value = ({"stored": True}, None)
    runner = ContinuousCaptureRunner(registry=registry(), capture=capture)
    with pytest.raises(ValueError, match="cadence"):
        runner.run(
            session_id="session-1", user_id="tenant-a", source_id="camera-1",
            location="entry", frames=[frame(0), frame(0.5)],
        )
    assert capture.ingest.call_count == 1
