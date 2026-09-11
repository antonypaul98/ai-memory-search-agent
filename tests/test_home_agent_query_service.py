from __future__ import annotations

from datetime import datetime, timezone

from app.services.home_agent import HomeAgentQueryService, ObjectSighting


class RecordingStore:
    def __init__(self, sighting: ObjectSighting | None = None):
        self.sighting = sighting
        self.latest_calls = []
        self.history_calls = []

    def latest(self, **kwargs):
        self.latest_calls.append(kwargs)
        return self.sighting

    def history(self, **kwargs):
        self.history_calls.append(kwargs)
        return [self.sighting] if self.sighting else []


def _sighting() -> ObjectSighting:
    return ObjectSighting(
        object_name="keys",
        location="entry table",
        observed_at=datetime(2026, 9, 10, 22, 5, tzinfo=timezone.utc),
        confidence=0.91,
        source_id="camera-entry",
        evidence_id="frame-9",
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
    assert store.latest_calls == [
        {"user_id": "tenant-a", "object_name": "keys", "min_confidence": 0.8}
    ]


def test_where_is_returns_none_without_qualifying_sighting():
    store = RecordingStore()
    service = HomeAgentQueryService(store)

    assert service.where_is(user_id="tenant-a", object_name="wallet") is None
    assert store.latest_calls[0]["user_id"] == "tenant-a"


def test_history_preserves_tenant_scope_and_limits():
    store = RecordingStore(_sighting())
    service = HomeAgentQueryService(store)

    history = service.history(
        user_id="tenant-b",
        object_name="keys",
        min_confidence=0.6,
        limit=7,
    )

    assert history == [_sighting()]
    assert store.history_calls == [
        {
            "user_id": "tenant-b",
            "object_name": "keys",
            "min_confidence": 0.6,
            "limit": 7,
        }
    ]
