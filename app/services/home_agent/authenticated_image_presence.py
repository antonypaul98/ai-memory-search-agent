"""Bridge validated image-ingest batches into authenticated Home presence memory."""
from __future__ import annotations

from datetime import datetime

from .authenticated_frame_presence import AuthenticatedFramePresenceBridge
from .image_ingest import ImageObservationBatch
from .presence_events import HomePresenceEvent


class AuthenticatedImagePresenceBridge:
    """Reuse validated image output without bypassing capture-session authentication."""

    def __init__(self, *, frame_bridge: AuthenticatedFramePresenceBridge):
        self._frame_bridge = frame_bridge

    def ingest_batch(
        self,
        *,
        session_id: str,
        user_id: str,
        batch: ImageObservationBatch,
        now: datetime | None = None,
        min_confidence: float = 0.8,
        confirmations: int = 2,
    ) -> HomePresenceEvent | None:
        if batch.user_id != user_id:
            raise PermissionError("image batch tenant does not match authenticated tenant")
        return self._frame_bridge.ingest_frames(
            session_id=session_id,
            user_id=user_id,
            source_id=batch.source_id,
            frames=[(batch.detections, batch.observed_at, batch.frame_id)],
            now=now,
            min_confidence=min_confidence,
            confirmations=confirmations,
        )
