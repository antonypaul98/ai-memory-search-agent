"""Core physical-memory data structures for Home Agent.

The first milestone is deliberately sensor-agnostic: camera/vision adapters may
produce sightings, but this module only stores and resolves observations that
already passed an explicit consent boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ObjectSighting:
    """One evidence-backed observation of a physical object."""

    object_name: str
    location: str
    observed_at: datetime
    confidence: float
    source_id: str
    evidence_id: str

    def __post_init__(self) -> None:
        name = self.object_name.strip()
        location = self.location.strip()
        source = self.source_id.strip()
        evidence = self.evidence_id.strip()
        if not name:
            raise ValueError("object_name must not be empty")
        if not location:
            raise ValueError("location must not be empty")
        if not source:
            raise ValueError("source_id must not be empty")
        if not evidence:
            raise ValueError("evidence_id must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")

        object.__setattr__(self, "object_name", name)
        object.__setattr__(self, "location", location)
        object.__setattr__(self, "source_id", source)
        object.__setattr__(self, "evidence_id", evidence)

    @property
    def observed_at_utc(self) -> datetime:
        return self.observed_at.astimezone(timezone.utc)


class PhysicalMemoryIndex:
    """Deterministic in-memory index for Home Agent object sightings.

    This is the minimal queryable core used before adding persistence, vision
    adapters, and voice/API surfaces. Retrieval is tenant-neutral for now; the
    persistence milestone must add tenant ownership before external exposure.
    """

    def __init__(self, sightings: Iterable[ObjectSighting] = ()) -> None:
        self._sightings: list[ObjectSighting] = []
        self._evidence_ids: set[str] = set()
        for sighting in sightings:
            self.add(sighting)

    def add(self, sighting: ObjectSighting) -> bool:
        """Add a sighting once, deduplicated by immutable evidence ID."""
        if sighting.evidence_id in self._evidence_ids:
            return False
        self._sightings.append(sighting)
        self._evidence_ids.add(sighting.evidence_id)
        return True

    def latest(self, object_name: str, *, min_confidence: float = 0.0) -> ObjectSighting | None:
        """Return the newest qualifying sighting for an object name."""
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0.0 and 1.0")
        needle = object_name.strip().casefold()
        if not needle:
            raise ValueError("object_name must not be empty")

        matches = (
            item
            for item in self._sightings
            if item.object_name.casefold() == needle and item.confidence >= min_confidence
        )
        return max(matches, key=lambda item: item.observed_at_utc, default=None)

    def history(self, object_name: str) -> list[ObjectSighting]:
        """Return newest-first history for an object."""
        needle = object_name.strip().casefold()
        if not needle:
            raise ValueError("object_name must not be empty")
        matches = [item for item in self._sightings if item.object_name.casefold() == needle]
        return sorted(matches, key=lambda item: item.observed_at_utc, reverse=True)

    def answer_where(self, object_name: str, *, min_confidence: float = 0.5) -> str | None:
        """Provide a deterministic answer suitable for a later voice/API layer."""
        sighting = self.latest(object_name, min_confidence=min_confidence)
        if sighting is None:
            return None
        stamp = sighting.observed_at.isoformat()
        return f"{sighting.object_name} was last seen at {sighting.location} at {stamp}."
