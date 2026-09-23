from unittest.mock import Mock

import pytest

from app.services.home_agent.opencv_camera import OpenCVCameraDevice


class Encoded:
    def __init__(self, value=b"jpeg"):
        self.value = value

    def tobytes(self):
        return self.value


def test_camera_opens_reads_encodes_and_releases():
    capture = Mock()
    capture.isOpened.return_value = True
    capture.read.return_value = (True, object())
    factory = Mock(return_value=capture)
    encoder = Mock(return_value=(True, Encoded(b"frame")))
    device = OpenCVCameraDevice(device_index=2, capture_factory=factory, encoder=encoder)
    device.open()
    assert device.read() == b"frame"
    device.close()
    factory.assert_called_once_with(2)
    encoder.assert_called_once()
    capture.release.assert_called_once_with()


def test_failed_camera_open_releases_handle_and_fails_closed():
    capture = Mock()
    capture.isOpened.return_value = False
    device = OpenCVCameraDevice(capture_factory=Mock(return_value=capture), encoder=Mock())
    with pytest.raises(RuntimeError, match="unable to open"):
        device.open()
    capture.release.assert_called_once_with()


def test_end_of_camera_stream_returns_none():
    capture = Mock()
    capture.isOpened.return_value = True
    capture.read.return_value = (False, None)
    device = OpenCVCameraDevice(capture_factory=Mock(return_value=capture), encoder=Mock())
    device.open()
    assert device.read() is None
    device.close()


def test_encode_failure_raises_and_close_releases_camera():
    capture = Mock()
    capture.isOpened.return_value = True
    capture.read.return_value = (True, object())
    device = OpenCVCameraDevice(
        capture_factory=Mock(return_value=capture), encoder=Mock(return_value=(False, None))
    )
    device.open()
    with pytest.raises(RuntimeError, match="failed to encode"):
        device.read()
    device.close()
    capture.release.assert_called_once_with()
