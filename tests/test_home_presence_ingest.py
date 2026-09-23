from datetime import datetime, timedelta, timezone

import pytest

from app.services.home_agent.observation_ingest import ObservationConsent, PHYSICAL_OBSERVATION_SCOPE
from app.services.home_agent.presence_derivation import PresenceObservation
from app.services.home_agent.presence_ingest import HomePresenceIngestService

NOW = datetime(2026, 9, 23, 4, 0, tzinfo=timezone.utc)


def obs(state: str, minute: int, source: str = "front-door-camera") -> PresenceObservation:
    return PresenceObservation(
        state=state,
        observed_at_utc=NOW - timedelta(minutes=3 - minute),
        confidence=0.95,
        source_id=source,
        evidence_id=f"frame-{minute}",
    )


def consent(user="tenant-a", source="front-door-camera") -> ObservationConsent:
    return ObservationConsent(
        user_id=user, source_id=source, scope=PHYSICAL_OBSERVATION_SCOPE,
        granted_at=NOW - timedelta(hours=1),
    )


class Store:
    def __init__(self): self.calls = []
    def store_presence_event(self, **kwargs): self.calls.append(kwargs); return True


def test_persists_only_confirmed_consent_bound_transition():
    store = Store()
    event = HomePresenceIngestService(store).ingest(
        user_id="tenant-a", observations=[obs("home", 0), obs("away", 1), obs("away", 2)],
        consent=consent(), now=NOW,
    )
    assert event is not None and event.kind == "home_departure"
    assert store.calls == [{"user_id": "tenant-a", "event": event}]


def test_noise_fails_closed_without_write():
    store = Store()
    event = HomePresenceIngestService(store).ingest(
        user_id="tenant-a", observations=[obs("home", 0), obs("away", 1), obs("home", 2)],
        consent=consent(), now=NOW,
    )
    assert event is None and store.calls == []


def test_tenant_or_source_consent_mismatch_is_rejected():
    service = HomePresenceIngestService(Store())
    with pytest.raises(PermissionError):
        service.ingest(user_id="tenant-b", observations=[obs("home", 0)], consent=consent(), now=NOW)
    with pytest.raises(PermissionError):
        service.ingest(user_id="tenant-a", observations=[obs("home", 0, "garage-camera")], consent=consent(), now=NOW)


def test_mixed_sources_are_rejected_before_derivation():
    with pytest.raises(ValueError):
        HomePresenceIngestService(Store()).ingest(
            user_id="tenant-a", observations=[obs("home", 0), obs("away", 1, "garage-camera")],
            consent=consent(), now=NOW,
        )
