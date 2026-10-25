"""Conservative, tenant-scoped location-change evidence for known object instances.

This is an offline derivation boundary, not an identity recognizer or a camera
pipeline. An upstream, authorized identity verifier must supply instance IDs,
confidence and association evidence. A location change is NOT an observed pickup,
a verified mover, or proof of the route taken between sightings.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Iterable


@dataclass(frozen=True, slots=True)
class InstanceObservation:
    user_id: str
    object_class: str
    location: str
    observed_at: datetime
    source_id: str
    evidence_id: str
    instance_id: str | None = None
    identity_evidence_id: str | None = None
    identity_confidence: float | None = None

    def __post_init__(self) -> None:
        for field in ("user_id", "object_class", "location", "source_id", "evidence_id"):
            if not isinstance(getattr(self, field), str) or not getattr(self, field).strip():
                raise ValueError(f"{field} is required")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.identity_confidence is not None:
            if (isinstance(self.identity_confidence, bool)
                    or not isinstance(self.identity_confidence, (int, float))
                    or not isfinite(self.identity_confidence)
                    or not 0 <= self.identity_confidence <= 1):
                raise ValueError("identity_confidence must be finite and between 0 and 1")


@dataclass(frozen=True, slots=True)
class ObservedLocationChange:
    user_id: str
    instance_id: str
    object_class: str
    from_location: str
    to_location: str
    last_seen_from: datetime
    first_seen_to: datetime
    from_evidence_id: str
    to_evidence_id: str
    from_identity_evidence_id: str
    to_identity_evidence_id: str


def derive_observed_location_changes(
    observations: Iterable[InstanceObservation], *, user_id: str,
    min_identity_confidence: float = 0.9,
    max_gap: timedelta = timedelta(minutes=5),
) -> list[ObservedLocationChange]:
    """Return only bounded, identity-evidenced changes in *observed* location.

    No transition is inferred from a class label alone. Conflicting sightings of
    one instance at the same instant, unverified identity, class changes, and
    blind gaps break continuity rather than producing a movement assertion.
    """
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id is required")
    if (isinstance(min_identity_confidence, bool)
            or not isinstance(min_identity_confidence, (int, float))
            or not isfinite(min_identity_confidence)
            or not 0 <= min_identity_confidence <= 1):
        raise ValueError("min_identity_confidence must be finite and between 0 and 1")
    if not isinstance(max_gap, timedelta) or not timedelta(0) < max_gap <= timedelta(minutes=5):
        raise ValueError("max_gap must be positive and at most five minutes")

    by_instance: dict[str, list[InstanceObservation]] = {}
    for observation in observations:
        if observation.user_id != user_id or not observation.instance_id or not observation.instance_id.strip():
            continue
        by_instance.setdefault(observation.instance_id, []).append(observation)

    changes: list[ObservedLocationChange] = []
    for instance_id, sightings in by_instance.items():
        ordered = sorted(sightings, key=lambda s: (s.observed_at, s.evidence_id))
        previous: InstanceObservation | None = None
        index = 0
        while index < len(ordered):
            current = ordered[index]
            same_time = [current]
            index += 1
            while index < len(ordered) and ordered[index].observed_at == current.observed_at:
                same_time.append(ordered[index])
                index += 1
            # An identity collision at the same instant makes the entire
            # time slice ambiguous. Do not link across it.
            if len({(s.object_class.casefold(), s.location.casefold()) for s in same_time}) > 1:
                previous = None
                continue
            # Deterministic selection; no observation is trusted without its
            # own association provenance and sufficient identity confidence.
            eligible = [s for s in same_time if (
                s.identity_evidence_id and s.identity_evidence_id.strip()
                and s.identity_confidence is not None
                and s.identity_confidence >= min_identity_confidence
            )]
            if len(eligible) != len(same_time):
                previous = None
                continue
            current = min(eligible, key=lambda s: s.evidence_id)
            if previous is not None:
                gap = current.observed_at - previous.observed_at
                if (timedelta(0) < gap <= max_gap
                        and current.object_class.casefold() == previous.object_class.casefold()
                        and current.location.casefold() != previous.location.casefold()):
                    changes.append(ObservedLocationChange(
                        user_id=user_id, instance_id=instance_id,
                        object_class=current.object_class,
                        from_location=previous.location, to_location=current.location,
                        last_seen_from=previous.observed_at, first_seen_to=current.observed_at,
                        from_evidence_id=previous.evidence_id, to_evidence_id=current.evidence_id,
                        from_identity_evidence_id=previous.identity_evidence_id,
                        to_identity_evidence_id=current.identity_evidence_id,
                    ))
            previous = current
    return sorted(changes, key=lambda c: (c.first_seen_to, c.instance_id, c.to_evidence_id))
