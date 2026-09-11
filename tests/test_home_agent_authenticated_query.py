from __future__ import annotations

from datetime import datetime, timezone

from app.models.user import UserPublic
from app.services.home_agent.authenticated_query import AuthenticatedHomeAgentQuery
from app.services.home_agent.query_service import HomeAgentQueryService
from app.services.home_agent.physical_memory import ObjectSighting


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
        observed_at=datetime(2026, 9, 11, 3, 55, tzinfo=timezone.utc),
        confidence=0.93,
        source_id="camera-entry",
        evidence_id="frame-11",
    )


def test_where_is_uses_authenticated_user_identity_only():
    store = RecordingStore(_sighting())
    boundary = AuthenticatedHomeAgentQuery(
        service=HomeAgentQueryService(store),
        user=UserPublic(user_id="tenant-authenticated", display_name="Antony"),
    )

    answer = boundary.where_is(object_name="keys", min_confidence=0.8)

    assert answer is not None
    assert answer.location == "entry table"
    assert store.latest_calls == [
        {
            "user_id": "tenant-authenticated",
            "object_name": "keys",
            "min_confidence": 0.8,
        }
    ]


def test_history_cannot_accept_caller_supplied_user_id():
    store = RecordingStore(_sighting())
    boundary = AuthenticatedHomeAgentQuery(
        service=HomeAgentQueryService(store),
        user=UserPublic(user_id="tenant-a"),
    )

    history = boundary.history(object_name="keys", limit=5)

    assert history == [_sighting()]
    assert store.history_calls == [
        {
            "user_id": "tenant-a",
            "object_name": "keys",
            "min_confidence": 0.0,
            "limit": 5,
        }
    ]
