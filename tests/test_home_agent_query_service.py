from __future__ import annotations

from datetime import datetime, timezone

from app.services.home_agent import HomeAgentQueryService, ObjectSighting


class RecordingStore:
    def __init__(self, sighting: ObjectSighting | None = None, history=None):
        self.sighting = sighting
        self._history = history
        self.latest_calls = []
        self.history_calls = []

    def latest(self, **kwargs):
        self.latest_calls.append(kwargs)
        return self.sighting

    def history(self, **kwargs):
        self.history_calls.append(kwargs)
        if self._history is not None:
            return self._history
        return [self.sighting] if self.sighting else []


def _sighting(location="entry table", minute=5, evidence_id="frame-9", confidence=0.91) -> ObjectSighting:
    return ObjectSighting(
        object_name="keys", location=location,
        observed_at=datetime(2026, 9, 10, 22, minute, tzinfo=timezone.utc),
        confidence=confidence, source_id="camera-entry", evidence_id=evidence_id,
    )


def test_where_is_routes_exact_tenant_and_returns_provenance():
    store = RecordingStore(_sighting())
    service = HomeAgentQueryService(store)
    answer = service.where_is(user_id="tenant-a", object_name="keys", min_confidence=0.8)
    assert answer is not None
    assert answer.location == "entry table"
    assert answer.source_id == "camera-entry"
    assert answer.evidence_id == "frame-9"
    assert answer.text == "keys was last seen at entry table at 2026-09-10T22:05:00+00:00."
    assert store.latest_calls == [{"user_id": "tenant-a", "object_name": "keys", "min_confidence": 0.8}]


def test_where_is_returns_none_without_qualifying_sighting():
    store = RecordingStore()
    service = HomeAgentQueryService(store)
    assert service.where_is(user_id="tenant-a", object_name="wallet") is None
    assert store.latest_calls[0]["user_id"] == "tenant-a"


def test_history_preserves_tenant_scope_and_limits():
    store = RecordingStore(_sighting())
    service = HomeAgentQueryService(store)
    history = service.history(user_id="tenant-b", object_name="keys", min_confidence=0.6, limit=7)
    assert history == [_sighting()]
    assert store.history_calls == [{"user_id": "tenant-b", "object_name": "keys", "min_confidence": 0.6, "limit": 7}]


def test_movement_history_collapses_same_location_and_preserves_evidence_chain():
    history = [
        _sighting("kitchen", 9, "frame-kitchen-new", 0.96),
        _sighting("kitchen", 8, "frame-kitchen-first", 0.94),
        _sighting("desk", 2, "frame-desk", 0.92),
    ]
    store = RecordingStore(history=history)
    service = HomeAgentQueryService(store)
    events = service.movement_history(user_id="tenant-a", object_name="KEYS", min_confidence=0.8, limit=10)
    assert len(events) == 1
    event = events[0]
    assert event.from_location == "desk"
    assert event.to_location == "kitchen"
    assert event.from_evidence_id == "frame-desk"
    assert event.to_evidence_id == "frame-kitchen-first"
    assert event.moved_at == "2026-09-10T22:08:00+00:00"
    assert store.history_calls == [{"user_id": "tenant-a", "object_name": "KEYS", "min_confidence": 0.8, "limit": 10}]


def test_before_location_returns_most_recent_matching_transition_with_evidence():
    history = [
        _sighting("kitchen", 12, "frame-kitchen-2", 0.97),
        _sighting("hall", 10, "frame-hall", 0.95),
        _sighting("kitchen", 8, "frame-kitchen-1", 0.94),
        _sighting("desk", 2, "frame-desk", 0.92),
    ]
    store = RecordingStore(history=history)
    service = HomeAgentQueryService(store)

    answer = service.before_location(
        user_id="tenant-a", object_name="keys", location=" KITCHEN ",
        min_confidence=0.8, limit=10,
    )

    assert answer is not None
    assert answer.location == "hall"
    assert answer.before_location == "kitchen"
    assert answer.evidence_id == "frame-hall"
    assert answer.destination_evidence_id == "frame-kitchen-2"
    assert answer.text == "keys was at hall before kitchen."
    assert store.history_calls == [{"user_id": "tenant-a", "object_name": "keys", "min_confidence": 0.8, "limit": 10}]


def test_before_location_returns_none_without_matching_transition():
    store = RecordingStore(history=[_sighting("desk", 2, "frame-desk")])
    service = HomeAgentQueryService(store)
    assert service.before_location(user_id="tenant-b", object_name="keys", location="kitchen") is None
    assert store.history_calls[0]["user_id"] == "tenant-b"
