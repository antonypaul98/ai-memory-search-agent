"""Structured vision adapter for Home Agent physical-memory ingestion.

This module does not access a camera or perform ambient capture. It accepts a
single already-produced vision detection, converts it into the canonical
ObjectSighting model, and routes persistence through the explicit-consent
boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .observation_ingest import HomeObservationIngestService, ObservationConsent
from .physical_memory import ObjectSighting


@dataclass(frozen=True, slots=True)
class VisionDetection:
    """One evidence-backed object detection produced by an external vision engine."""

    object_name: str
    location: str
    observed_at: datetime
    confidence: float
    source_id: str
    evidence_id: str

    def to_sighting(self) -> ObjectSighting:
        """Convert the detection into the canonical physical-memory record."""
        return ObjectSighting(
            object_name=self.object_name,
            location=self.location,
            observed_at=self.observed_at,
            confidence=self.confidence,
            source_id=self.source_id,
            evidence_id=self.evidence_id,
        )


class ConsentGatedVisionAdapter:
    """Route a vision detection through Home Agent's mandatory consent gate."""

    def __init__(self, ingest_service: HomeObservationIngestService) -> None:
        self._ingest_service = ingest_service

    def ingest_detection(
        self,
        *,
        user_id: str,
        detection: VisionDetection,
        consent: ObservationConsent,
        now: datetime | None = None,
    ) -> bool:
        sighting = detection.to_sighting()
        return self._ingest_service.ingest(
            user_id=user_id,
            sighting=sighting,
            consent=consent,
            now=now,
        )
