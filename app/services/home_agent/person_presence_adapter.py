"""Convert bounded person-detector output into Home Agent presence observations."""
from __future__ import annotations

from datetime import datetime
from typing import Sequence

from .image_ingest import DetectedObject
from .presence_derivation import PresenceObservation


def presence_observation_from_detections(
    *,
    detections: Sequence[DetectedObject],
    observed_at: datetime,
    source_id: str,
    evidence_id: str,
    person_class: str = "person",
) -> PresenceObservation:
    """Adapt one detector frame to a provenance-preserving presence observation.

    Presence means at least one detection exactly matching ``person_class``. An
    empty/non-person frame becomes ``away`` with confidence based on the strongest
    detector evidence against presence. This adapter does not persist anything;
    authenticated session validation remains the responsibility of the ingestion
    boundary.
    """
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    if not source_id.strip() or not evidence_id.strip():
        raise ValueError("source_id and evidence_id are required")
    target = " ".join(person_class.split()).casefold()
    if not target:
        raise ValueError("person_class is required")
    if any(not isinstance(item, DetectedObject) for item in detections):
        raise ValueError("detections must contain DetectedObject values")

    matches = [item for item in detections if item.object_class == target]
    if matches:
        confidence = max(item.confidence for item in matches)
        state = "home"
    else:
        strongest = max((item.confidence for item in detections), default=0.0)
        confidence = max(0.0, 1.0 - strongest)
        state = "away"

    return PresenceObservation(
        state=state,
        observed_at_utc=observed_at,
        confidence=confidence,
        source_id=source_id,
        evidence_id=evidence_id,
    )
