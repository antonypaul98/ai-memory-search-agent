from datetime import timedelta
from unittest.mock import Mock

import pytest

from app.services.home_agent.continuous_capture import CaptureRunResult
from app.services.home_agent.frame_source import FrameSourceResult
from app.services.home_agent.hardware_smoke import run_hardware_smoke


def test_hardware_smoke_routes_bounded_authenticated_probe_and_reports_pass():
    capture = Mock()
    capture.run.return_value = FrameSourceResult(
        capture=CaptureRunResult(2, (), "frame_limit"), source_closed=True
    )

    result = run_hardware_smoke(
        capture=capture,
        session_id="session-1",
        user_id="tenant-a",
        source_id="camera-1",
        location="entry",
        device_index=2,
        max_frames=2,
        min_interval=timedelta(seconds=2),
        min_confidence=0.9,
        confirmations=3,
    )

    capture.run.assert_called_once_with(
        session_id="session-1",
        user_id="tenant-a",
        source_id="camera-1",
        location="entry",
        device_index=2,
        max_frames=2,
        min_interval=timedelta(seconds=2),
        min_confidence=0.9,
        confirmations=3,
    )
    assert result.passed is True
    assert result.frames_processed == 2
    assert result.events_emitted == 0
    assert result.source_closed is True
    assert result.event_required is False


def test_hardware_smoke_strict_mode_requires_physical_memory_event():
    capture = Mock()
    capture.run.return_value = FrameSourceResult(
        capture=CaptureRunResult(2, (), "frame_limit"), source_closed=True
    )

    result = run_hardware_smoke(
        capture=capture,
        session_id="session-1",
        user_id="tenant-a",
        source_id="camera-1",
        location="entry",
        require_event=True,
    )

    assert result.passed is False
    assert result.event_required is True
    assert result.events_emitted == 0


def test_hardware_smoke_strict_mode_passes_when_event_is_emitted():
    capture = Mock()
    event = Mock()
    capture.run.return_value = FrameSourceResult(
        capture=CaptureRunResult(2, (event,), "frame_limit"), source_closed=True
    )

    result = run_hardware_smoke(
        capture=capture,
        session_id="session-1",
        user_id="tenant-a",
        source_id="camera-1",
        location="entry",
        require_event=True,
    )

    assert result.passed is True
    assert result.events_emitted == 1


def test_hardware_smoke_does_not_pass_without_frame_or_cleanup():
    capture = Mock()
    capture.run.return_value = FrameSourceResult(
        capture=CaptureRunResult(0, (), "source_exhausted"), source_closed=False
    )

    result = run_hardware_smoke(
        capture=capture,
        session_id="session-1",
        user_id="tenant-a",
        source_id="camera-1",
        location="entry",
    )

    assert result.passed is False


def test_hardware_smoke_rejects_invalid_bound_before_camera_access():
    capture = Mock()
    with pytest.raises(ValueError, match="max_frames"):
        run_hardware_smoke(
            capture=capture,
            session_id="session-1",
            user_id="tenant-a",
            source_id="camera-1",
            location="entry",
            max_frames=0,
        )
    capture.run.assert_not_called()
