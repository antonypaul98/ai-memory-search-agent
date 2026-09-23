"""Bridge authenticated detector-frame output into the Home presence pipeline."""
from __future__ import annotations

from datetime import datetime
from typing import Sequence

from .authenticated_presence_ingest import AuthenticatedHomePresenceIngest
from .image_ingest import DetectedObject
from .person_presence_adapter import presence_observation_from_detections
from .presence_derivation import PresenceObservation
from .presence_events import HomePresenceEvent


class AuthenticatedFramePresenceBridge:
    """Adapt detector frames, then reuse the authenticated presence boundary."""

    def __init__(self, *, presence_ingest: AuthenticatedHomePresenceIngest):
        self._presence_ingest = presence_ingest

    def ingest_frames(
        self,
        *,
        session_id: str,
        user_id: str,
        source_id: str,
        frames: Sequence[tuple[Sequence[DetectedObject], datetime, str]],
        now: datetime | None = None,
        min_confidence: float = 0.8,
        confirmations: int = 2,
    ) -> HomePresenceEvent | None:
        """Convert bounded frame detections without bypassing session authentication."""
        observations: list[PresenceObservation] = []
        for detections, observed_at, evidence_id in frames:
            observations.append(
                presence_observation_from_detections(
                    detections=detections,
                    observed_at=observed_at,
                    source_id=source_id,
                    evidence_id=evidence_id,
                )
            )
        return self._presence_ingest.ingest(
            session_id=session_id,
            user_id=user_id,
            source_id=source_id,
            observations=observations,
            now=now,
            min_confidence=min_confidence,
            confirmations=confirmations,
        )
