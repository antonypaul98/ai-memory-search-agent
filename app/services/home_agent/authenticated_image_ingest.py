"""Bind raw still-image ingestion to a server-owned authenticated capture session."""
from __future__ import annotations

from datetime import datetime, timezone

from .capture_registry import CaptureSessionRegistry
from .image_ingest import HomeImageIngestService
from .observation_ingest import ObservationConsent, PHYSICAL_OBSERVATION_SCOPE


class AuthenticatedHomeImageIngest:
    """Fail closed unless the image belongs to the caller's active capture session."""

    def __init__(self, *, registry: CaptureSessionRegistry, image_ingest: HomeImageIngestService):
        self._registry = registry
        self._image_ingest = image_ingest

    def ingest(
        self,
        *,
        session_id: str,
        user_id: str,
        source_id: str,
        image_bytes: bytes,
        location: str,
        observed_at: datetime,
        now: datetime | None = None,
    ) -> dict:
        now = now or datetime.now(timezone.utc)
        session = self._registry.resolve(
            session_id=session_id,
            user_id=user_id,
            source_id=source_id,
            now=now,
        )
        consent = ObservationConsent(
            user_id=user_id,
            source_id=session.source_id,
            scope=PHYSICAL_OBSERVATION_SCOPE,
            granted_at=session.started_at,
            expires_at=session.expires_at,
        )
        return self._image_ingest.ingest(
            user_id=user_id,
            image_bytes=image_bytes,
            source_id=session.source_id,
            location=location,
            observed_at=observed_at,
            consent=consent,
            now=now,
        )
