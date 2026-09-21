"""Regression coverage for trusted Home Agent observation timestamps."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.home_agent.observation_ingest import (
    HomeObservationIngestService,
    ObservationConsent,
    PHYSICAL_OBSERVATION_SCOPE,
)
from app.services.home_agent.physical_memory import ObjectSighting


class _Store:
    def __init__(self) -> None:
        self.items = []

    def store_sighting(self, *, user_id: str, sighting: ObjectSighting) -> bool:
        self.items.append((user_id, sighting))
        return True


def _consent(now: datetime) -> ObservationConsent:
    return ObservationConsent(
        user_id="tenant-a",
        source_id="camera-1",
        scope=PHYSICAL_OBSERVATION_SCOPE,
        granted_at=now - timedelta(minutes=5),
        expires_at=now + timedelta(minutes=5),
    )


def _sighting(observed_at: datetime) -> ObjectSighting:
    return ObjectSighting(
        object_name="keys",
        location="entry table",
        observed_at=observed_at,
        confidence=0.9,
        source_id="camera-1",
        evidence_id=f"frame-{observed_at.timestamp()}",
    )


def test_ingest_rejects_observation_from_far_future() -> None:
    now = datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)
    store = _Store()
    service = HomeObservationIngestService(store)

    with pytest.raises(ValueError, match="observation timestamp"):
        service.ingest(
            user_id="tenant-a",
            sighting=_sighting(now + timedelta(minutes=10)),
            consent=_consent(now),
            now=now,
        )
    assert store.items == []


def test_ingest_accepts_small_device_clock_skew() -> None:
    now = datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)
    store = _Store()
    service = HomeObservationIngestService(store)

    assert service.ingest(
        user_id="tenant-a",
        sighting=_sighting(now + timedelta(seconds=30)),
        consent=_consent(now),
        now=now,
    ) is True
    assert len(store.items) == 1
