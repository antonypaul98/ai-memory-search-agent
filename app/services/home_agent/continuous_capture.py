"""Bounded continuous capture for authenticated Home Agent sessions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from .authenticated_image_capture import AuthenticatedImageCapture
from .capture_registry import CaptureSessionRegistry
from .presence_events import HomePresenceEvent


@dataclass(frozen=True)
class CaptureFrame:
    image_bytes: bytes
    observed_at: datetime


@dataclass(frozen=True)
class CaptureRunResult:
    frames_processed: int
    events: tuple[HomePresenceEvent, ...]
    stopped_reason: str


class ContinuousCaptureRunner:
    """Consume a bounded frame stream while an authenticated session stays active.

    The caller owns camera I/O and timing. This runner deliberately revalidates the
    server-owned session before every frame and rejects frames arriving faster than
    the configured cadence instead of sleeping or extending session lifetime.
    """

    def __init__(self, *, registry: CaptureSessionRegistry, capture: AuthenticatedImageCapture):
        self._registry = registry
        self._capture = capture

    def run(
        self, *, session_id: str, user_id: str, source_id: str, location: str,
        frames: Iterable[CaptureFrame], min_interval: timedelta = timedelta(seconds=1),
        max_frames: int = 300, min_confidence: float = 0.8, confirmations: int = 2,
    ) -> CaptureRunResult:
        if min_interval.total_seconds() <= 0:
            raise ValueError("min_interval must be positive")
        if max_frames < 1:
            raise ValueError("max_frames must be >= 1")

        processed = 0
        events: list[HomePresenceEvent] = []
        previous_at: datetime | None = None
        iterator = iter(frames)
        while processed < max_frames:
            try:
                frame = next(iterator)
            except StopIteration:
                return CaptureRunResult(processed, tuple(events), "source_exhausted")
            if frame.observed_at.tzinfo is None or frame.observed_at.utcoffset() is None:
                raise ValueError("frame observed_at must be timezone-aware")
            if previous_at is not None and frame.observed_at - previous_at < min_interval:
                raise ValueError("capture frame cadence is faster than allowed")
            try:
                self._registry.resolve(
                    session_id=session_id, user_id=user_id, source_id=source_id,
                    now=frame.observed_at,
                )
            except PermissionError:
                return CaptureRunResult(processed, tuple(events), "session_inactive")

            _, event = self._capture.ingest(
                session_id=session_id, user_id=user_id, source_id=source_id,
                image_bytes=frame.image_bytes, location=location,
                observed_at=frame.observed_at, now=frame.observed_at,
                min_confidence=min_confidence, confirmations=confirmations,
            )
            processed += 1
            previous_at = frame.observed_at
            if event is not None:
                events.append(event)

        return CaptureRunResult(processed, tuple(events), "frame_limit")
