"""Conservative derivation of home presence transitions from trusted evidence.

This module deliberately does not persist events. It turns a bounded sequence of
presence observations into a candidate HomePresenceEvent only when a stable
state transition is supported by evidence on both sides of the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Sequence

from .presence_events import HomePresenceEvent

PresenceState = Literal["home", "away"]


@dataclass(frozen=True)
class PresenceObservation:
    state: PresenceState
    observed_at_utc: datetime
    confidence: float
    source_id: str
    evidence_id: str

    def __post_init__(self) -> None:
        if self.state not in ("home", "away"):
            raise ValueError("unsupported presence state")
        if self.observed_at_utc.tzinfo is None or self.observed_at_utc.utcoffset() is None:
            raise ValueError("observed_at_utc must be timezone-aware")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        if not self.source_id.strip() or not self.evidence_id.strip():
            raise ValueError("source_id and evidence_id are required")
        object.__setattr__(self, "observed_at_utc", self.observed_at_utc.astimezone(timezone.utc))
        object.__setattr__(self, "source_id", self.source_id.strip())
        object.__setattr__(self, "evidence_id", self.evidence_id.strip())


def derive_presence_transition(
    observations: Sequence[PresenceObservation],
    *,
    min_confidence: float = 0.8,
    confirmations: int = 2,
) -> HomePresenceEvent | None:
    """Return the newest confirmed transition, otherwise fail closed.

    A transition requires one qualified observation of the prior state followed
    by ``confirmations`` qualified observations of the opposite state. This
    prevents a single noisy frame/sensor reading from becoming a departure or
    arrival anchor. The event timestamp and provenance come from the first
    observation of the confirmed new state.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError("min_confidence must be between 0.0 and 1.0")
    if confirmations < 1:
        raise ValueError("confirmations must be at least 1")

    qualified = sorted(
        (o for o in observations if o.confidence >= min_confidence),
        key=lambda o: o.observed_at_utc,
    )
    if len(qualified) < confirmations + 1:
        return None

    candidate: HomePresenceEvent | None = None
    for index, previous in enumerate(qualified[:-confirmations]):
        window = qualified[index + 1 : index + 1 + confirmations]
        if not window or window[0].state == previous.state:
            continue
        new_state = window[0].state
        if any(item.state != new_state for item in window):
            continue
        first = window[0]
        candidate = HomePresenceEvent(
            kind="home_departure" if new_state == "away" else "home_arrival",
            occurred_at_utc=first.observed_at_utc,
            confidence=min(item.confidence for item in window),
            source_id=first.source_id,
            evidence_id=first.evidence_id,
        )
    return candidate
