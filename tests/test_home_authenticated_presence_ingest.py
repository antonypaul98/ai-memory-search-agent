from datetime import datetime, timedelta, timezone

import pytest

from app.services.home_agent.authenticated_presence_ingest import AuthenticatedHomePresenceIngest
from app.services.home_agent.capture_registry import CaptureSessionRegistry
from app.services.home_agent.capture_session import CaptureSession
from app.services.home_agent.presence_derivation import PresenceObservation
from app.services.home_agent.presence_ingest import HomePresenceIngestService

NOW = datetime(2026, 9, 23, 6, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self): self.calls = []
    def store_presence_event(self, **kwargs): self.calls.append(kwargs); return True


def session(*, user="tenant-a", source="front-door-camera"):
    return CaptureSession(
        session_id="session-1", user_id=user, source_id=source,
        started_at=NOW - timedelta(minutes=10), expires_at=NOW + timedelta(minutes=10),
    )


def obs(state, minute, source="front-door-camera"):
    return PresenceObservation(
        state=state, observed_at_utc=NOW - timedelta(minutes=3-minute),
        confidence=0.95, source_id=source, evidence_id=f"frame-{minute}",
    )


def service(registry, store):
    return AuthenticatedHomePresenceIngest(
        registry=registry, presence_ingest=HomePresenceIngestService(store)
    )


def test_authenticated_session_can_persist_confirmed_transition():
    registry = CaptureSessionRegistry(); registry.register(session()); store = Store()
    event = service(registry, store).ingest(
        session_id="session-1", user_id="tenant-a", source_id="front-door-camera",
        observations=[obs("home", 0), obs("away", 1), obs("away", 2)], now=NOW,
    )
    assert event is not None and event.kind == "home_departure"
    assert len(store.calls) == 1 and store.calls[0]["user_id"] == "tenant-a"


def test_wrong_tenant_or_source_fails_before_write():
    registry = CaptureSessionRegistry(); registry.register(session()); store = Store()
    with pytest.raises(PermissionError):
        service(registry, store).ingest(
            session_id="session-1", user_id="tenant-b", source_id="front-door-camera",
            observations=[obs("home", 0)], now=NOW,
        )
    with pytest.raises(PermissionError):
        service(registry, store).ingest(
            session_id="session-1", user_id="tenant-a", source_id="garage-camera",
            observations=[obs("home", 0, "garage-camera")], now=NOW,
        )
    assert store.calls == []


def test_evidence_source_must_match_authenticated_session():
    registry = CaptureSessionRegistry(); registry.register(session()); store = Store()
    with pytest.raises(PermissionError):
        service(registry, store).ingest(
            session_id="session-1", user_id="tenant-a", source_id="front-door-camera",
            observations=[obs("home", 0), obs("away", 1, "garage-camera")], now=NOW,
        )
    assert store.calls == []


def test_expired_session_fails_before_write():
    registry = CaptureSessionRegistry()
    expired = CaptureSession(
        session_id="session-1", user_id="tenant-a", source_id="front-door-camera",
        started_at=NOW - timedelta(hours=2), expires_at=NOW - timedelta(hours=1),
    )
    registry.register(expired); store = Store()
    with pytest.raises(PermissionError):
        service(registry, store).ingest(
            session_id="session-1", user_id="tenant-a", source_id="front-door-camera",
            observations=[obs("home", 0)], now=NOW,
        )
    assert store.calls == []
