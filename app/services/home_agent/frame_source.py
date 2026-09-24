"""Lifecycle-controlled frame sources for Home Agent continuous capture."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from time import sleep
from typing import Callable, Iterator, Protocol

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
    """Open a device lazily, pace/timestamp frames, and always close it."""

    def __init__(
        self, *, device: FrameDevice, clock: Callable[[], datetime],
        min_interval: timedelta | None = None, sleeper: Callable[[float], None] = sleep,
    ):
        if min_interval is not None and min_interval.total_seconds() <= 0:
            raise ValueError("min_interval must be positive")
        self._device = device
        self._clock = clock
        self._min_interval = min_interval
        self._sleeper = sleeper
        self.closed = False

    def __iter__(self) -> Iterator[CaptureFrame]:
        self._device.open()
        first = True
        try:
            while True:
                if not first and self._min_interval is not None:
                    self._sleeper(self._min_interval.total_seconds())
                image_bytes = self._device.read()
                if image_bytes is None:
                    return
                observed_at = self._clock()
                if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                    raise ValueError("frame source clock must return timezone-aware timestamps")
                yield CaptureFrame(image_bytes=image_bytes, observed_at=observed_at)
                first = False
        finally:
            self._device.close()
            self.closed = True


class ContinuousCaptureSourceAdapter:
    """Bind lifecycle-controlled camera I/O to the authenticated capture runner."""

    def __init__(
        self, *, runner: ContinuousCaptureRunner,
        sleeper: Callable[[float], None] = sleep,
    ):
        self._runner = runner
        self._sleeper = sleeper

    def run_device(
        self, *, device: FrameDevice, clock: Callable[[], datetime], session_id: str,
        user_id: str, source_id: str, location: str, **runner_kwargs,
    ) -> FrameSourceResult:
        min_interval = runner_kwargs.get("min_interval", timedelta(seconds=1))
        stream = DeviceFrameStream(
            device=device, clock=clock, min_interval=min_interval, sleeper=self._sleeper,
        )
        capture = self._runner.run(
            session_id=session_id, user_id=user_id, source_id=source_id,
            location=location, frames=stream, **runner_kwargs,
        )
        return FrameSourceResult(capture=capture, source_closed=stream.closed)
