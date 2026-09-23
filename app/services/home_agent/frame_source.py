"""Lifecycle-controlled frame sources for Home Agent continuous capture."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable, Iterator, Protocol

from .continuous_capture import CaptureFrame, CaptureRunResult, ContinuousCaptureRunner


class FrameDevice(Protocol):
    """Minimal device contract; concrete camera backends stay outside core capture."""

    def open(self) -> None: ...
    def read(self) -> bytes | None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class FrameSourceResult:
    capture: CaptureRunResult
    source_closed: bool


class DeviceFrameStream:
    """Open a device lazily, timestamp frames, and always close it on termination."""

    def __init__(self, *, device: FrameDevice, clock: Callable[[], datetime]):
        self._device = device
        self._clock = clock
        self.closed = False

    def __iter__(self) -> Iterator[CaptureFrame]:
        self._device.open()
        try:
            while True:
                image_bytes = self._device.read()
                if image_bytes is None:
                    return
                observed_at = self._clock()
                if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                    raise ValueError("frame source clock must return timezone-aware timestamps")
                yield CaptureFrame(image_bytes=image_bytes, observed_at=observed_at)
        finally:
            self._device.close()
            self.closed = True


class ContinuousCaptureSourceAdapter:
    """Bind lifecycle-controlled camera I/O to the authenticated capture runner."""

    def __init__(self, *, runner: ContinuousCaptureRunner):
        self._runner = runner

    def run_device(
        self, *, device: FrameDevice, clock: Callable[[], datetime], session_id: str,
        user_id: str, source_id: str, location: str, **runner_kwargs,
    ) -> FrameSourceResult:
        stream = DeviceFrameStream(device=device, clock=clock)
        capture = self._runner.run(
            session_id=session_id, user_id=user_id, source_id=source_id,
            location=location, frames=stream, **runner_kwargs,
        )
        return FrameSourceResult(capture=capture, source_closed=stream.closed)
