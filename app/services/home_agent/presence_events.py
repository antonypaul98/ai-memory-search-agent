"""Evidence-backed Home Agent presence-event primitives.

Presence events are explicit anchors for event-relative physical-memory queries.
They must come from a concrete source/evidence record; callers must not synthesize
or infer a departure timestamp when evidence is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

PresenceEventKind = Literal["home_departure", "home_arrival"]


@dataclass(frozen=True)
class HomePresenceEvent:
    """A tenant-owned, evidence-backed home presence transition."""

    kind: PresenceEventKind
    occurred_at_utc: datetime
    confidence: float
    source_id: str
    evidence_id: str

    def __post_init__(self) -> None:
        if self.kind not in ("home_departure", "home_arrival"):
            raise ValueError("unsupported presence event kind")
        if self.occurred_at_utc.tzinfo is None or self.occurred_at_utc.utcoffset() is None:
            raise ValueError("occurred_at_utc must be timezone-aware")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        if not self.source_id.strip():
            raise ValueError("source_id is required")
        if not self.evidence_id.strip():
            raise ValueError("evidence_id is required")

        object.__setattr__(self, "occurred_at_utc", self.occurred_at_utc.astimezone(timezone.utc))
        object.__setattr__(self, "source_id", self.source_id.strip())
        object.__setattr__(self, "evidence_id", self.evidence_id.strip())
