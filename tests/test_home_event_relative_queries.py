"""Safety regressions for event-relative Home/Jarvis physical-memory questions."""
from datetime import datetime, timezone
from app.services.home_agent.natural_language import HomeQueryIntent, parse_home_query
from app.services.home_agent.physical_memory import ObjectSighting
from app.services.home_agent.presence_events import HomePresenceEvent
from app.services.home_agent.query_service import HomeAgentQueryService

def test_departure_relative_queries_parse_to_explicit_intent():
    assert parse_home_query("Where were my keys before I left home?") == HomeQueryIntent(kind="before_departure", object_name="keys")
    assert parse_home_query("Where was my wallet before I departed my home?") == HomeQueryIntent(kind="before_departure", object_name="wallet")
    assert parse_home_query("Where did I last see my keys before I left the home?") == HomeQueryIntent(kind="before_departure", object_name="keys")

def test_existing_before_location_query_remains_supported():
    assert parse_home_query("Where were my keys before the kitchen?") == HomeQueryIntent(kind="before_location", object_name="keys", location="kitchen")

class _Store:
    def __init__(self, *, tenant="alice", departure=True): self.tenant=tenant; self.departure=departure
    def latest_presence_event(self, *, user_id, kind, min_confidence):
        if user_id != self.tenant or not self.departure: return None
        return HomePresenceEvent(kind="home_departure", occurred_at_utc=datetime(2026,9,22,12,tzinfo=timezone.utc), confidence=.9, source_id="door", evidence_id="dep-1")
    def history(self, *, user_id, object_name, min_confidence=0.0, limit=20):
        if user_id != self.tenant: return []
        return [
            ObjectSighting(object_name,"car",datetime(2026,9,22,13,tzinfo=timezone.utc),.9,"cam","after"),
            ObjectSighting(object_name,"desk",datetime(2026,9,22,11,tzinfo=timezone.utc),.9,"cam","before"),
        ][:limit]

def test_departure_query_uses_latest_tenant_owned_verified_anchor():
    answer=HomeAgentQueryService(_Store()).where_is_before_departure(user_id="alice",object_name="keys")
    assert answer is not None
    assert answer.location == "desk"
    assert answer.evidence_id == "before"

def test_departure_query_fails_closed_without_anchor_or_for_neighbor_tenant():
    assert HomeAgentQueryService(_Store(departure=False)).where_is_before_departure(user_id="alice",object_name="keys") is None
    assert HomeAgentQueryService(_Store()).where_is_before_departure(user_id="bob",object_name="keys") is None
