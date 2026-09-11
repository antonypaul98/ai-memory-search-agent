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

    @property
    def text(self) -> str:
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
        return WhereAnswer(
            object_name=sighting.object_name,
            location=sighting.location,
            observed_at=sighting.observed_at.isoformat(),
            confidence=sighting.confidence,
            source_id=sighting.source_id,
            evidence_id=sighting.evidence_id,
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
