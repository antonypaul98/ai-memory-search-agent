"""Session-aware orchestration for validated image capture and presence memory."""
from __future__ import annotations

from datetime import datetime

from .authenticated_image_presence import AuthenticatedImagePresenceBridge
from .capture_registry import CaptureSessionRegistry
from .image_ingest import HomeImageIngestService, ImageObservationBatch
from .observation_ingest import ObservationConsent, PHYSICAL_OBSERVATION_SCOPE
from .presence_events import HomePresenceEvent


class _CapturingWriter:
    """Delegate image persistence while retaining the exact validated batch."""

    def __init__(self, delegate):
        self._delegate = delegate
        self.batch: ImageObservationBatch | None = None

    def store_image_batch(self, batch: ImageObservationBatch) -> dict:
        result = self._delegate.store_image_batch(batch)
        self.batch = batch
        return result


class AuthenticatedImageCapture:
    """Run image ingest and presence derivation under one active capture session."""

    def __init__(self, *, registry: CaptureSessionRegistry, image_store, detector,
                 presence_bridge: AuthenticatedImagePresenceBridge):
        self._registry = registry
        self._image_store = image_store
        self._detector = detector
        self._presence_bridge = presence_bridge

    def ingest(self, *, session_id: str, user_id: str, source_id: str,
               image_bytes: bytes, location: str, observed_at: datetime,
               now: datetime | None = None, min_confidence: float = 0.8,
               confirmations: int = 2) -> tuple[dict, HomePresenceEvent | None]:
        session = self._registry.resolve(
            session_id=session_id, user_id=user_id, source_id=source_id, now=now,
        )
        consent = ObservationConsent(
            user_id=user_id, source_id=session.source_id,
            scope=PHYSICAL_OBSERVATION_SCOPE, granted_at=session.started_at,
            expires_at=session.expires_at,
        )
        writer = _CapturingWriter(self._image_store)
        result = HomeImageIngestService(writer, self._detector).ingest(
            user_id=user_id, image_bytes=image_bytes, source_id=source_id,
            location=location, observed_at=observed_at, consent=consent, now=now,
        )
        if writer.batch is None:
            raise RuntimeError("validated image ingest did not persist a batch")
        event = self._presence_bridge.ingest_batch(
            session_id=session_id, user_id=user_id, batch=writer.batch, now=now,
            min_confidence=min_confidence, confirmations=confirmations,
        )
        return result, event
