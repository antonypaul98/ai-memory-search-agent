"""Bridge validated image-ingest batches into authenticated Home presence memory."""
from __future__ import annotations

from collections import OrderedDict, deque
from datetime import datetime

from .authenticated_frame_presence import AuthenticatedFramePresenceBridge
from .image_ingest import ImageObservationBatch
from .presence_events import HomePresenceEvent


class AuthenticatedImagePresenceBridge:
    """Reuse validated image output without bypassing capture-session authentication."""

    def __init__(
        self,
        *,
        frame_bridge: AuthenticatedFramePresenceBridge,
        max_streams: int = 128,
        max_frames_per_stream: int = 32,
    ):
        if max_streams < 1:
            raise ValueError("max_streams must be at least 1")
        if max_frames_per_stream < 2:
            raise ValueError("max_frames_per_stream must be at least 2")
        self._frame_bridge = frame_bridge
        self._max_streams = max_streams
        self._max_frames_per_stream = max_frames_per_stream
        self._frame_history = OrderedDict()

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
        if confirmations < 1:
            raise ValueError("confirmations must be at least 1")
        required_frames = confirmations + 1
        if required_frames > self._max_frames_per_stream:
            raise ValueError("confirmations exceed bounded frame history")

        stream_key = (session_id, user_id, batch.source_id)
        history = self._frame_history.get(stream_key)
        if history is None:
            if len(self._frame_history) >= self._max_streams:
                self._frame_history.popitem(last=False)
            history = deque(maxlen=self._max_frames_per_stream)
            self._frame_history[stream_key] = history
        else:
            self._frame_history.move_to_end(stream_key)

        history.append((batch.detections, batch.observed_at, batch.frame_id))
        frames = list(history)[-required_frames:]
        return self._frame_bridge.ingest_frames(
            session_id=session_id,
            user_id=user_id,
            source_id=batch.source_id,
            frames=frames,
            now=now,
            min_confidence=min_confidence,
            confirmations=confirmations,
        )
