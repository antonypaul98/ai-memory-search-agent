"""Bind presence observations to a server-owned authenticated capture session."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from .capture_registry import CaptureSessionRegistry
from .observation_ingest import ObservationConsent, PHYSICAL_OBSERVATION_SCOPE
from .presence_derivation import PresenceObservation
from .presence_events import HomePresenceEvent
from .presence_ingest import HomePresenceIngestService


class AuthenticatedHomePresenceIngest:
    """Fail closed unless presence evidence belongs to an active capture session."""

    def __init__(self, *, registry: CaptureSessionRegistry, presence_ingest: HomePresenceIngestService):
        self._registry = registry
        self._presence_ingest = presence_ingest

    def ingest(
        self,
        *,
        session_id: str,
        user_id: str,
        source_id: str,
        observations: Sequence[PresenceObservation],
        now: datetime | None = None,
        min_confidence: float = 0.8,
        confirmations: int = 2,
    ) -> HomePresenceEvent | None:
        resolved_now = now or datetime.now(timezone.utc)
        session = self._registry.resolve(
            session_id=session_id,
            user_id=user_id,
            source_id=source_id,
            now=resolved_now,
        )
        if any(observation.source_id != session.source_id for observation in observations):
            raise PermissionError("presence evidence source does not match authenticated capture session")
        consent = ObservationConsent(
            user_id=user_id,
            source_id=session.source_id,
            scope=PHYSICAL_OBSERVATION_SCOPE,
            granted_at=session.started_at,
            expires_at=session.expires_at,
        )
        return self._presence_ingest.ingest(
            user_id=user_id,
            observations=observations,
            consent=consent,
            now=resolved_now,
            min_confidence=min_confidence,
            confirmations=confirmations,
        )
