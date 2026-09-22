from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.home_agent.event_relative import where_before_latest_departure
from app.services.home_agent.natural_language import parse_home_query
from app.services.home_agent.presence_events import HomePresenceEvent


class Store:
    def __init__(self, departure):
        self.departure = departure
        self.calls = []

    def latest_presence_event(self, **kwargs):
        self.calls.append(kwargs)
        return self.departure


class Service:
    def __init__(self, store):
        self._store = store
        self.calls = []

    def where_is_between(self, **kwargs):
        self.calls.append(kwargs)
        return "answer"


def _departure():
    return HomePresenceEvent(
        kind="home_departure",
        occurred_at_utc=datetime(2026, 9, 22, 14, 30, tzinfo=timezone.utc),
        confidence=0.94,
        source_id="front-door-camera",
        evidence_id="departure-1",
    )


def test_parser_recognizes_departure_relative_question():
    intent = parse_home_query("Where were my keys before I left home?")
    assert intent is not None
    assert intent.kind == "before_departure"
    assert intent.object_name == "keys"


def test_departure_query_uses_authenticated_tenant_and_strict_upper_bound():
    store = Store(_departure())
    service = Service(store)
    query = SimpleNamespace(service=service, user=SimpleNamespace(user_id="tenant-a"))

    assert where_before_latest_departure(query=query, object_name="keys", min_confidence=0.8) == "answer"
    assert store.calls == [{"user_id": "tenant-a", "kind": "home_departure", "min_confidence": 0.8}]
    call = service.calls[0]
    assert call["user_id"] == "tenant-a"
    assert call["object_name"] == "keys"
    assert call["until"] == _departure().occurred_at_utc


def test_departure_query_fails_closed_without_verified_anchor():
    store = Store(None)
    service = Service(store)
    query = SimpleNamespace(service=service, user=SimpleNamespace(user_id="tenant-a"))

    assert where_before_latest_departure(query=query, object_name="keys") is None
    assert service.calls == []
