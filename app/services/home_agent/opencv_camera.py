"""Optional OpenCV camera backend for Home Agent frame capture."""
from __future__ import annotations

from typing import Any, Callable


class OpenCVCameraDevice:
    """FrameDevice backed by OpenCV VideoCapture with explicit lifecycle control."""

    def __init__(
        self,
        *,
        device_index: int = 0,
        capture_factory: Callable[[int], Any] | None = None,
        encoder: Callable[[str, Any], tuple[bool, Any]] | None = None,
        image_format: str = ".jpg",
    ) -> None:
        self._device_index = device_index
        self._capture_factory = capture_factory
        self._encoder = encoder
        self._image_format = image_format
        self._capture: Any | None = None

    def _bindings(self) -> tuple[Callable[[int], Any], Callable[[str, Any], tuple[bool, Any]]]:
        if self._capture_factory is not None and self._encoder is not None:
            return self._capture_factory, self._encoder
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("OpenCV camera backend requires optional dependency 'opencv-python'") from exc
        return self._capture_factory or cv2.VideoCapture, self._encoder or cv2.imencode

    def open(self) -> None:
        if self._capture is not None:
            raise RuntimeError("camera is already open")
        capture_factory, encoder = self._bindings()
        capture = capture_factory(self._device_index)
        if not capture.isOpened():
            capture.release()
            raise RuntimeError(f"unable to open camera device {self._device_index}")
        self._encoder = encoder
        self._capture = capture

    def read(self) -> bytes | None:
        if self._capture is None or self._encoder is None:
            raise RuntimeError("camera must be opened before reading")
        ok, frame = self._capture.read()
        if not ok:
            return None
        encoded_ok, encoded = self._encoder(self._image_format, frame)
        if not encoded_ok:
            raise RuntimeError("failed to encode camera frame")
        return encoded.tobytes()

    def close(self) -> None:
        capture, self._capture = self._capture, None
        if capture is not None:
            capture.release()
