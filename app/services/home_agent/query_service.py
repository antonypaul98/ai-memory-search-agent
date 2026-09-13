"""Tenant-scoped query layer for persisted Home Agent physical memory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .physical_memory import ObjectSighting


class PhysicalMemoryStore(Protocol):
    def latest(
        self,
        *,
        user_id: str,
        object_name: str,
        min_confidence: float = 0.0,
    ) -> ObjectSighting | None: ...

    def history(
        self,
        *,
        user_id: str,
        object_name: str,
        min_confidence: float = 0.0,
        limit: int = 20,
    ) -> list[ObjectSighting]: ...


@dataclass(frozen=True, slots=True)
class WhereAnswer:
    object_name: str
    location: str
    observed_at: str
    confidence: float
    source_id: str
    evidence_id: str
    conflicting_locations: tuple[str, ...] = ()
    history_truncated: bool = False

    @property
    def text(self) -> str:
        if self.conflicting_locations:
            places = ", ".join(self.conflicting_locations)
            return f"{self.object_name} has conflicting observations at {self.observed_at}: {places}. Its location is uncertain."
        if self.history_truncated:
            return f"{self.object_name} was observed at {self.location} at {self.observed_at}; additional simultaneous observations may exist."
        return f"{self.object_name} was last seen at {self.location} at {self.observed_at}."


class HomeAgentQueryService:
    """Resolve Home Agent questions without crossing tenant boundaries."""

    def __init__(self, store: PhysicalMemoryStore) -> None:
        self._store = store

    def where_is(
        self,
        *,
        user_id: str,
        object_name: str,
        min_confidence: float = 0.5,
    ) -> WhereAnswer | None:
        sighting = self._store.latest(
            user_id=user_id,
            object_name=object_name,
            min_confidence=min_confidence,
        )
        if sighting is None:
            return None
        recent = self._store.history(user_id=user_id, object_name=object_name,
                                     min_confidence=min_confidence, limit=100)
        locations = {sighting.location}
        locations.update(item.location for item in recent
                         if item.observed_at_utc == sighting.observed_at_utc)
        # A bounded history can omit other same-time observations; do not turn
        # a full page into an assertion that the selected location is unique.
        truncated = len(recent) == 100 and recent[-1].observed_at_utc == sighting.observed_at_utc
        return WhereAnswer(
            object_name=sighting.object_name,
            location=sighting.location,
            observed_at=sighting.observed_at.isoformat(),
            confidence=sighting.confidence,
            source_id=sighting.source_id,
            evidence_id=sighting.evidence_id,
            conflicting_locations=tuple(sorted(locations)) if len(locations) > 1 else (),
            history_truncated=truncated,
        )

    def history(
        self,
        *,
        user_id: str,
        object_name: str,
        min_confidence: float = 0.0,
        limit: int = 20,
    ) -> list[ObjectSighting]:
        return self._store.history(
            user_id=user_id,
            object_name=object_name,
            min_confidence=min_confidence,
            limit=limit,
        )
