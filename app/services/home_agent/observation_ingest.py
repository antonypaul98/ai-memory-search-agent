"""Consent-gated ingestion boundary for Home Agent physical observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from .physical_memory import ObjectSighting


PHYSICAL_OBSERVATION_SCOPE = "home_agent.physical_observation"


class PhysicalMemoryWriter(Protocol):
    def store_sighting(self, *, user_id: str, sighting: ObjectSighting) -> bool: ...


@dataclass(frozen=True, slots=True)
class ObservationConsent:
    """Explicit, source-scoped permission for storing Home Agent observations."""

    user_id: str
    source_id: str
    scope: str
    granted_at: datetime
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.user_id.strip():
            raise ValueError("user_id is required")
        if not self.source_id.strip():
            raise ValueError("source_id is required")
        if not self.scope.strip():
            raise ValueError("scope is required")
        if self.granted_at.tzinfo is None or self.granted_at.utcoffset() is None:
            raise ValueError("granted_at must be timezone-aware")
        if self.expires_at is not None:
            if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
                raise ValueError("expires_at must be timezone-aware")
            if self.expires_at <= self.granted_at:
                raise ValueError("expires_at must be after granted_at")

    def allows(self, *, user_id: str, source_id: str, now: datetime) -> bool:
        if self.scope != PHYSICAL_OBSERVATION_SCOPE:
            return False
        if self.user_id != user_id or self.source_id != source_id:
            return False
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return self.expires_at is None or now < self.expires_at


class HomeObservationIngestService:
    """Persist sightings only after explicit tenant- and source-bound consent."""

    def __init__(self, store: PhysicalMemoryWriter) -> None:
        self._store = store

    def ingest(
        self,
        *,
        user_id: str,
        sighting: ObjectSighting,
        consent: ObservationConsent,
        now: datetime | None = None,
    ) -> bool:
        resolved_now = now or datetime.now(timezone.utc)
        if not consent.allows(
            user_id=user_id,
            source_id=sighting.source_id,
            now=resolved_now,
        ):
            raise PermissionError("physical observation consent is missing, mismatched, or expired")
        return self._store.store_sighting(user_id=user_id, sighting=sighting)
