"""Opt-in, frame-bounded camera-to-image-memory bridge (not instance identity).

Reuses the existing camera device, capture-session registry, and authenticated
still-image ingestion. No preview track, optical-flow box, or class detection
becomes a verified physical-instance association through this bridge.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import sleep
from typing import Callable

from .authenticated_image_ingest import AuthenticatedHomeImageIngest
from .capture_registry import CaptureSessionRegistry
from .frame_source import DeviceFrameStream, FrameDevice


def _persisted_frame_id(result: dict) -> str | None:
    """Interpret explicit storage evidence; never count unknown results as stored.

    The PostgreSQL store reports observation and retained-byte counts, while
    older test stores report an explicit boolean. Do not infer persistence
    from a frame ID alone: duplicates return an existing frame ID.
    """
    if not isinstance(result, dict):
        raise ValueError("invalid image persistence result")
    frame_id = result.get("frame_id")
    if "stored_observations" in result or "retained_bytes" in result:
        observations = result.get("stored_observations")
        retained_bytes = result.get("retained_bytes")
        if (type(observations) is not int or observations < 0
                or type(retained_bytes) is not int or retained_bytes < 0):
            raise ValueError("invalid image persistence counters")
        if (observations > 0) != (retained_bytes > 0):
            raise ValueError("inconsistent image persistence counters")
        was_stored = observations > 0
        if "stored" in result and (
                type(result["stored"]) is not bool or result["stored"] != was_stored):
            raise ValueError("conflicting image persistence flags")
    else:
        if type(result.get("stored")) is not bool:
            raise ValueError("image persistence result lacks explicit status")
        was_stored = result["stored"]
    if was_stored:
        if not isinstance(frame_id, str) or not frame_id.strip():
            raise ValueError("stored image has no valid frame ID")
        return frame_id
    return None


@dataclass(frozen=True)
class ImageCaptureResult:
    frames_processed: int
    frames_stored: int
    frame_ids: tuple[str, ...]
    source_closed: bool


class ImageCaptureBridge:
    """Store at most 30 consented camera frames through existing image ingestion.

    The caller must explicitly start a server-owned capture session. Camera I/O
    is only opened after verifying tenant/source/session; every frame is checked
    again before image ingestion. No automatic identity association is created.
    """

    def __init__(
        self, *, registry: CaptureSessionRegistry,
        image_ingest: AuthenticatedHomeImageIngest,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        self._registry = registry
        self._image_ingest = image_ingest
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sleeper = sleeper

    def run_device(
        self, *, device: FrameDevice, session_id: str, user_id: str,
        source_id: str, location: str, max_frames: int = 3,
        min_interval: timedelta = timedelta(seconds=1),
    ) -> ImageCaptureResult:
        if type(max_frames) is not int or not 1 <= max_frames <= 30:
            raise ValueError("max_frames must be between 1 and 30")
        if (not isinstance(min_interval, timedelta)
                or not timedelta(milliseconds=200) <= min_interval <= timedelta(minutes=1)):
            raise ValueError("min_interval must be between 0.2 and 60 seconds")
        if not isinstance(location, str) or not location.strip():
            raise ValueError("explicit location is required")
        # No camera access before server-owned session authorization.
        self._registry.resolve(session_id=session_id, user_id=user_id,
                               source_id=source_id, now=self._clock())
        stream = DeviceFrameStream(device=device, clock=self._clock,
                                   min_interval=min_interval, sleeper=self._sleeper)
        iterator = iter(stream)
        processed = 0
        stored = 0
        frame_ids: list[str] = []
        try:
            for _ in range(max_frames):
                try:
                    frame = next(iterator)
                except StopIteration:
                    break
                now = self._clock()
                session = self._registry.resolve(
                    session_id=session_id, user_id=user_id, source_id=source_id, now=now,
                )
                if not session.allows(user_id=user_id, source_id=source_id,
                                      observed_at=frame.observed_at, now=now):
                    raise PermissionError("frame is outside the active capture session")
                result = self._image_ingest.ingest(
                    session_id=session_id, user_id=user_id, source_id=source_id,
                    image_bytes=frame.image_bytes, location=location,
                    observed_at=frame.observed_at, now=now,
                )
                processed += 1
                frame_id = _persisted_frame_id(result)
                if frame_id is not None:
                    stored += 1
                    frame_ids.append(frame_id)
        finally:
            iterator.close()
        return ImageCaptureResult(processed, stored, tuple(frame_ids), stream.closed)

    def run_camera(self, *, device_index: int = 0, device_factory=None, **kwargs) -> ImageCaptureResult:
        """Opt-in OpenCV device entrypoint; device factory is injectable for tests."""
        if type(device_index) is not int or device_index < 0:
            raise ValueError("device_index must be a non-negative integer")
        if device_factory is None:
            from .opencv_camera import OpenCVCameraDevice
            device_factory = OpenCVCameraDevice
        return self.run_device(device=device_factory(device_index=device_index), **kwargs)
