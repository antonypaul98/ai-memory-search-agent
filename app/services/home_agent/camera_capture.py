"""Concrete camera entrypoint for authenticated Home Agent capture."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from .frame_source import ContinuousCaptureSourceAdapter, FrameSourceResult
from .opencv_camera import OpenCVCameraDevice


class OpenCVCameraCapture:
    """Bind an OpenCV camera device to the authenticated continuous-capture adapter.

    Construction stays dependency-injectable so camera hardware is only touched when
    ``run`` is called and tests do not require OpenCV or a physical camera.
    """

    def __init__(
        self,
        *,
        adapter: ContinuousCaptureSourceAdapter,
        device_factory: Callable[..., OpenCVCameraDevice] = OpenCVCameraDevice,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._adapter = adapter
        self._device_factory = device_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def run(
        self,
        *,
        session_id: str,
        user_id: str,
        source_id: str,
        location: str,
        device_index: int = 0,
        **runner_kwargs,
    ) -> FrameSourceResult:
        if device_index < 0:
            raise ValueError("device_index must be >= 0")
        device = self._device_factory(device_index=device_index)
        return self._adapter.run_device(
            device=device,
            clock=self._clock,
            session_id=session_id,
            user_id=user_id,
            source_id=source_id,
            location=location,
            **runner_kwargs,
        )
