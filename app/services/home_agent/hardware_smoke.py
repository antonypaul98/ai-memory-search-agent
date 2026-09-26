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

    def failure_reasons(self) -> tuple[str, ...]:
        """Explain exactly which hardware-acceptance conditions are still unmet."""
        reasons: list[str] = []
        if self.frames_processed < 1:
            reasons.append("no_frames_processed")
        if not self.source_closed:
            reasons.append("camera_source_not_closed")
        if self.event_required and self.events_emitted < 1:
            reasons.append("required_physical_memory_event_not_emitted")
        return tuple(reasons)

    @property
    def passed(self) -> bool:
        return not self.failure_reasons()

def run_hardware_smoke(
    *, capture: OpenCVCameraCapture, session_id: str, user_id: str,
    source_id: str, location: str, device_index: int = 0,
    max_frames: int = 3, min_interval: timedelta = timedelta(seconds=1),
    min_confidence: float = 0.8, confirmations: int = 2,
    require_event: bool = False,
) -> HardwareSmokeResult:
    """Run a bounded real-camera acceptance probe through authenticated capture."""
    if max_frames < 1:
        raise ValueError("max_frames must be >= 1")
    result: FrameSourceResult = capture.run(
        session_id=session_id, user_id=user_id, source_id=source_id,
        location=location, device_index=device_index, max_frames=max_frames,
        min_interval=min_interval, min_confidence=min_confidence,
        confirmations=confirmations,
    )
    return HardwareSmokeResult(
        frames_processed=result.capture.frames_processed,
        events_emitted=len(result.capture.events),
        stopped_reason=result.capture.stopped_reason,
        source_closed=result.source_closed,
        event_required=require_event,
    )
