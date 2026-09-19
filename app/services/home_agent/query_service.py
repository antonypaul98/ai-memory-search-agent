"""Tenant-scoped query layer for persisted Home Agent physical memory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .physical_memory import ObjectSighting


class PhysicalMemoryStore(Protocol):
    def latest(self, *, user_id: str, object_name: str, min_confidence: float = 0.0) -> ObjectSighting | None: ...
    def history(self, *, user_id: str, object_name: str, min_confidence: float = 0.0, limit: int = 20) -> list[ObjectSighting]: ...


class InspectableEvidenceStore(Protocol):
    def describe_observation(self, *, user_id: str, observation_id: str) -> dict | None: ...
    def get_image(self, *, user_id: str, frame_id: str) -> bytes | None: ...


@dataclass(frozen=True, slots=True)
class WhereAnswer:
    object_name: str
    location: str
    observed_at: str
    confidence: float
    source_id: str
    evidence_id: str
    evidence_frame_id: str | None = None
    evidence_image_sha256: str | None = None
    evidence_detector_id: str | None = None

    @property
    def text(self) -> str:
        return f"{self.object_name} was last seen at {self.location} at {self.observed_at}."


@dataclass(frozen=True, slots=True)
class MovementEvent:
    """Evidence-linked transition between two observed locations."""
    object_name: str
    from_location: str
    to_location: str
    moved_at: str
    confidence: float
    source_id: str
    from_evidence_id: str
    to_evidence_id: str


@dataclass(frozen=True, slots=True)
class BeforeLocationAnswer:
    """Answer where an object was immediately before an observed destination."""
    object_name: str
    location: str
    before_location: str
    moved_at: str
    confidence: float
    source_id: str
    evidence_id: str
    destination_evidence_id: str

    @property
    def text(self) -> str:
        return f"{self.object_name} was at {self.location} before {self.before_location}."


class HomeAgentQueryService:
    """Resolve Home Agent questions without crossing tenant boundaries."""

    def __init__(self, store: PhysicalMemoryStore) -> None:
        self._store = store

    def where_is(self, *, user_id: str, object_name: str, min_confidence: float = 0.5) -> WhereAnswer | None:
        sighting = self._store.latest(user_id=user_id, object_name=object_name, min_confidence=min_confidence)
        if sighting is None:
            return None
        evidence = None
        describe = getattr(self._store, "describe_observation", None)
        if callable(describe):
            evidence = describe(user_id=user_id, observation_id=sighting.evidence_id)
        return WhereAnswer(
            object_name=sighting.object_name, location=sighting.location,
            observed_at=sighting.observed_at.isoformat(), confidence=sighting.confidence,
            source_id=sighting.source_id, evidence_id=sighting.evidence_id,
            evidence_frame_id=evidence.get("frame_id") if evidence else None,
            evidence_image_sha256=evidence.get("image_sha256") if evidence else None,
            evidence_detector_id=evidence.get("detector_id") if evidence else None,
        )

    def evidence_image(self, *, user_id: str, answer: WhereAnswer) -> bytes | None:
        if not answer.evidence_frame_id:
            return None
        return self.evidence_frame(user_id=user_id, frame_id=answer.evidence_frame_id)

    def evidence_frame(self, *, user_id: str, frame_id: str) -> bytes | None:
        if not frame_id.strip():
            return None
        get_image = getattr(self._store, "get_image", None)
        if not callable(get_image):
            return None
        return get_image(user_id=user_id, frame_id=frame_id)

    def history(self, *, user_id: str, object_name: str, min_confidence: float = 0.0, limit: int = 20) -> list[ObjectSighting]:
        return self._store.history(user_id=user_id, object_name=object_name, min_confidence=min_confidence, limit=limit)

    def movement_history(self, *, user_id: str, object_name: str, min_confidence: float = 0.5, limit: int = 20) -> list[MovementEvent]:
        """Return chronological location changes, preserving evidence on both sides."""
        sightings = self.history(user_id=user_id, object_name=object_name,
                                 min_confidence=min_confidence, limit=limit)
        chronological = list(reversed(sightings))
        events: list[MovementEvent] = []
        previous: ObjectSighting | None = None
        for current in chronological:
            if previous is not None and current.location != previous.location:
                events.append(MovementEvent(
                    object_name=current.object_name,
                    from_location=previous.location,
                    to_location=current.location,
                    moved_at=current.observed_at.isoformat(),
                    confidence=current.confidence,
                    source_id=current.source_id,
                    from_evidence_id=previous.evidence_id,
                    to_evidence_id=current.evidence_id,
                ))
            previous = current
        return events

    def before_location(self, *, user_id: str, object_name: str, location: str,
                        min_confidence: float = 0.5, limit: int = 20) -> BeforeLocationAnswer | None:
        """Return the most recent location immediately before entering ``location``.

        Matching is case-insensitive after trimming. The answer preserves evidence
        from both sides of the transition and inherits tenant isolation from the
        tenant-scoped movement history query.
        """
        target = location.strip().casefold()
        if not target:
            return None
        movements = self.movement_history(
            user_id=user_id, object_name=object_name,
            min_confidence=min_confidence, limit=limit,
        )
        for movement in reversed(movements):
            if movement.to_location.strip().casefold() == target:
                return BeforeLocationAnswer(
                    object_name=movement.object_name,
                    location=movement.from_location,
                    before_location=movement.to_location,
                    moved_at=movement.moved_at,
                    confidence=movement.confidence,
                    source_id=movement.source_id,
                    evidence_id=movement.from_evidence_id,
                    destination_evidence_id=movement.to_evidence_id,
                )
        return None
