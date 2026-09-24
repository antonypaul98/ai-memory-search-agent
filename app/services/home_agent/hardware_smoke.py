"""Acceptance contract for a real Home Agent camera smoke run."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from .camera_capture import OpenCVCameraCapture
from .frame_source import FrameSourceResult


@dataclass(frozen=True)
class HardwareSmokeResult:
    frames_processed: int
    events_emitted: int
    stopped_reason: str
    source_closed: bool
    event_required: bool = False

    @property
    def passed(self) -> bool:
        frame_and_cleanup_ok = self.frames_processed >= 1 and self.source_closed
        event_ok = not self.event_required or self.events_emitted >= 1
        return frame_and_cleanup_ok and event_ok


def run_hardware_smoke(
    *, capture: OpenCVCameraCapture, session_id: str, user_id: str,
    source_id: str, location: str, device_index: int = 0,
    max_frames: int = 3, min_interval: timedelta = timedelta(seconds=1),
    min_confidence: float = 0.8, confirmations: int = 2,
    require_event: bool = False,
) -> HardwareSmokeResult:
    """Run a bounded real-camera acceptance probe through authenticated capture.

    Passing proves at least one physical frame traversed the configured authenticated
    pipeline and that the frame source was released. By default presence events are
    reported but not required because their emission depends on what the camera sees.
    Set ``require_event`` for the stronger physical-memory acceptance run where the
    scene is deliberately arranged to produce a presence transition.
    """
    if max_frames < 1:
        raise ValueError("max_frames must be >= 1")

    result: FrameSourceResult = capture.run(
        session_id=session_id,
        user_id=user_id,
        source_id=source_id,
        location=location,
        device_index=device_index,
        max_frames=max_frames,
        min_interval=min_interval,
        min_confidence=min_confidence,
        confirmations=confirmations,
    )
    return HardwareSmokeResult(
        frames_processed=result.capture.frames_processed,
        events_emitted=len(result.capture.events),
        stopped_reason=result.capture.stopped_reason,
        source_closed=result.source_closed,
        event_required=require_event,
    )
