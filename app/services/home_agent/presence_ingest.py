"""Consent-gated derivation and persistence of Home Agent presence transitions."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol, Sequence

from .observation_ingest import ObservationConsent
from .presence_derivation import PresenceObservation, derive_presence_transition
from .presence_events import HomePresenceEvent


class PresenceEventWriter(Protocol):
    def store_presence_event(self, *, user_id: str, event: HomePresenceEvent) -> bool: ...


class HomePresenceIngestService:
    """Derive and persist a transition only from consented, tenant-bound evidence."""

    def __init__(self, store: PresenceEventWriter) -> None:
        self._store = store

    def ingest(
        self,
        *,
        user_id: str,
        observations: Sequence[PresenceObservation],
        consent: ObservationConsent,
        now: datetime | None = None,
        min_confidence: float = 0.8,
        confirmations: int = 2,
    ) -> HomePresenceEvent | None:
        resolved_now = now or datetime.now(timezone.utc)
        if not observations:
            return None
        source_ids = {item.source_id for item in observations}
        if len(source_ids) != 1:
            raise ValueError("presence observations must come from one source")
        source_id = next(iter(source_ids))
        if not consent.allows(user_id=user_id, source_id=source_id, now=resolved_now):
            raise PermissionError("physical observation consent is missing, mismatched, or expired")
        event = derive_presence_transition(
            observations, min_confidence=min_confidence, confirmations=confirmations
        )
        if event is None:
            return None
        if event.occurred_at_utc > resolved_now.astimezone(timezone.utc):
            raise ValueError("derived presence event cannot be in the future")
        self._store.store_presence_event(user_id=user_id, event=event)
        return event
