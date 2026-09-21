"""Regression coverage for authenticated local-day physical-memory queries."""
from datetime import datetime, timezone

from app.models.user import UserPublic
from app.services.home_agent.authenticated_query import AuthenticatedHomeAgentQuery
from app.services.home_agent.physical_memory import ObjectSighting
from app.services.home_agent.query_service import HomeAgentQueryService


class _Store:
    def __init__(self, items):
        self.items = items

    def history(self, *, user_id, object_name, min_confidence=0.0, limit=20):
        return [s for tenant, s in self.items
                if tenant == user_id and s.object_name == object_name
                and s.confidence >= min_confidence][:limit]

    def latest(self, *, user_id, object_name, min_confidence=0.0):
        items = self.history(user_id=user_id, object_name=object_name,
                             min_confidence=min_confidence)
        return items[0] if items else None


def _sighting(location, observed_at, evidence):
    return ObjectSighting(object_name="keys", location=location,
                          observed_at=observed_at, confidence=0.9,
                          source_id="camera-1", evidence_id=evidence)


def test_where_is_today_uses_authenticated_timezone_and_tenant():
    # At 04:30 UTC it is 00:30 on Sep 21 in New York. A 03:30 UTC sighting
    # belongs to Sep 20 locally and must not win the "today" query.
    items = [
        ("tenant-a", _sighting("entry table", datetime(2026, 9, 21, 4, 15, tzinfo=timezone.utc), "today")),
        ("tenant-a", _sighting("garage", datetime(2026, 9, 21, 3, 30, tzinfo=timezone.utc), "yesterday")),
        ("tenant-b", _sighting("other tenant", datetime(2026, 9, 21, 4, 20, tzinfo=timezone.utc), "foreign")),
    ]
    query = AuthenticatedHomeAgentQuery(
        service=HomeAgentQueryService(_Store(items)),
        user=UserPublic(user_id="tenant-a", timezone_name="America/New_York"),
    )

    answer = query.where_is_today(
        object_name="keys",
        now=datetime(2026, 9, 21, 4, 30, tzinfo=timezone.utc),
    )

    assert answer is not None
    assert answer.location == "entry table"
    assert answer.evidence_id == "today"


def test_where_is_today_returns_none_when_only_previous_local_day_exists():
    items = [("tenant-a", _sighting("garage", datetime(2026, 9, 21, 3, 30, tzinfo=timezone.utc), "old"))]
    query = AuthenticatedHomeAgentQuery(
        service=HomeAgentQueryService(_Store(items)),
        user=UserPublic(user_id="tenant-a", timezone_name="America/New_York"),
    )
    assert query.where_is_today(
        object_name="keys",
        now=datetime(2026, 9, 21, 4, 30, tzinfo=timezone.utc),
    ) is None
