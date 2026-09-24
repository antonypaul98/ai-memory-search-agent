from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from app.services.home_agent.camera_capture import OpenCVCameraCapture
from app.services.home_agent.continuous_capture import CaptureRunResult
from app.services.home_agent.frame_source import FrameSourceResult

NOW = datetime(2026, 9, 24, 1, 0, tzinfo=timezone.utc)


def test_entrypoint_constructs_selected_camera_and_routes_authenticated_context():
    adapter = Mock()
    adapter.run_device.return_value = FrameSourceResult(
        capture=CaptureRunResult(1, (), "source_exhausted"), source_closed=True
    )
    device = Mock()
    factory = Mock(return_value=device)
    capture = OpenCVCameraCapture(adapter=adapter, device_factory=factory, clock=lambda: NOW)

    result = capture.run(
        session_id="session-1",
        user_id="tenant-a",
        source_id="camera-1",
        location="entry",
        device_index=2,
        max_frames=4,
    )

    factory.assert_called_once_with(device_index=2)
    call = adapter.run_device.call_args.kwargs
    assert call["device"] is device
    assert call["session_id"] == "session-1"
    assert call["user_id"] == "tenant-a"
    assert call["source_id"] == "camera-1"
    assert call["location"] == "entry"
    assert call["max_frames"] == 4
    assert call["clock"]() == NOW
    assert result.source_closed is True
    assert result.capture.frames_processed == 1


def test_entrypoint_is_lazy_and_rejects_invalid_device_before_hardware_access():
    adapter = Mock()
    factory = Mock()
    capture = OpenCVCameraCapture(adapter=adapter, device_factory=factory)

    factory.assert_not_called()
    with pytest.raises(ValueError, match="device_index"):
        capture.run(
            session_id="session-1",
            user_id="tenant-a",
            source_id="camera-1",
            location="entry",
            device_index=-1,
        )
    factory.assert_not_called()
    adapter.run_device.assert_not_called()
