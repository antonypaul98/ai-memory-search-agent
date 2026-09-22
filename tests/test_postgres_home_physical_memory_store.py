from __future__ import annotations

from tests.postgres_fence_fakes import is_fence_query, UnfencedCursor

from datetime import datetime, timezone

import pytest

from app.db.postgres_home_physical_memory_store import PostgresHomePhysicalMemoryStore
from app.services.home_agent import ObjectSighting
from app.services.home_agent.presence_events import HomePresenceEvent


class FakeResult:
    def __init__(self, *, one=None):
        self._one = one

    def fetchone(self):
        return self._one


class FakeConnection:
    def __init__(self, statements, results=None):
        self.statements = statements
        self.results = list(results or [])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement, params=None):
        if is_fence_query(statement):
            return UnfencedCursor()
        self.statements.append((" ".join(str(statement).split()), params))
        if self.results:
            return self.results.pop(0)
        return FakeResult()


def _sighting(*, evidence_id="frame-1") -> ObjectSighting:
    return ObjectSighting(
        object_name="keys",
        location="entry table",
        observed_at=datetime(2026, 9, 10, 22, 0, tzinfo=timezone.utc),
        confidence=0.91,
        source_id="camera-entry",
        evidence_id=evidence_id,
    )


def _departure(*, evidence_id="departure-1") -> HomePresenceEvent:
    return HomePresenceEvent(
        kind="home_departure",
        occurred_at_utc=datetime(2026, 9, 22, 14, 30, tzinfo=timezone.utc),
        confidence=0.94,
        source_id="front-door-camera",
        evidence_id=evidence_id,
    )


def test_schema_keys_evidence_by_tenant():
    statements = []
    PostgresHomePhysicalMemoryStore(lambda: FakeConnection(statements))

    sql = "\n".join(statement for statement, _ in statements)
    assert "PRIMARY KEY (user_id, evidence_id)" in sql
    assert "idx_home_object_sightings_lookup" in sql
    assert "ON home_object_sightings(user_id, object_name, observed_at DESC)" in sql
    assert "CREATE TABLE IF NOT EXISTS home_presence_events" in sql
    assert "idx_home_presence_events_lookup" in sql
    assert "ON home_presence_events(user_id, kind, occurred_at DESC)" in sql


def test_store_sighting_preserves_tenant_and_provenance():
    statements = []
    connections = iter(
        [
            FakeConnection(statements),
            FakeConnection(statements, [FakeResult(one={"evidence_id": "frame-1"})]),
        ]
    )
    store = PostgresHomePhysicalMemoryStore(lambda: next(connections))

    assert store.store_sighting(user_id="tenant-a", sighting=_sighting()) is True
    statement, params = statements[-1]
    assert "ON CONFLICT(user_id, evidence_id) DO NOTHING" in statement
    assert params[0] == "tenant-a"
    assert params[1] == "frame-1"
    assert params[2] == "keys"
    assert params[3] == "entry table"
    assert params[5] == 0.91
    assert params[6] == "camera-entry"


def test_store_presence_event_preserves_tenant_and_provenance():
    statements = []
    connections = iter([
        FakeConnection(statements),
        FakeConnection(statements, [FakeResult(one={"evidence_id": "departure-1"})]),
    ])
    store = PostgresHomePhysicalMemoryStore(lambda: next(connections))

    assert store.store_presence_event(user_id="tenant-a", event=_departure()) is True
    statement, params = statements[-1]
    assert "INSERT INTO home_presence_events" in statement
    assert "ON CONFLICT(user_id, evidence_id) DO NOTHING" in statement
    assert params[0] == "tenant-a"
    assert params[1] == "departure-1"
    assert params[2] == "home_departure"
    assert params[4] == 0.94
    assert params[5] == "front-door-camera"


def test_latest_departure_is_tenant_scoped_and_bounded():
    statements = []
    occurred = datetime(2026, 9, 22, 14, 30, tzinfo=timezone.utc)
    before = datetime(2026, 9, 22, 15, 0, tzinfo=timezone.utc)
    row = {"kind": "home_departure", "occurred_at": occurred, "confidence": 0.94,
           "source_id": "front-door-camera", "evidence_id": "departure-1"}
    connections = iter([FakeConnection(statements), FakeConnection(statements, [FakeResult(one=row)])])
    store = PostgresHomePhysicalMemoryStore(lambda: next(connections))

    result = store.latest_presence_event(user_id="tenant-a", kind="home_departure",
                                         min_confidence=0.8, before=before)
    assert result == _departure()
    statement, params = statements[-1]
    assert "WHERE user_id = %s AND kind = %s AND confidence >= %s" in statement
    assert "occurred_at < %s" in statement
    assert params == ("tenant-a", "home_departure", 0.8, before, before)


def test_duplicate_evidence_is_reported_without_overwrite():
    statements = []
    connections = iter([FakeConnection(statements), FakeConnection(statements, [FakeResult(one=None)])])
    store = PostgresHomePhysicalMemoryStore(lambda: next(connections))

    assert store.store_sighting(user_id="tenant-a", sighting=_sighting()) is False
    statement, _ = statements[-1]
    assert "DO NOTHING" in statement
    assert "DO UPDATE" not in statement


def test_latest_requires_exact_tenant_and_confidence():
    statements = []
    row = {
        "object_name": "keys",
        "location": "desk",
        "observed_at": "2026-09-10T22:05:00+00:00",
        "confidence": 0.88,
        "source_id": "camera-office",
        "evidence_id": "frame-9",
    }
    connections = iter(
        [
            FakeConnection(statements),
            FakeConnection(statements, [FakeResult(one=row)]),
        ]
    )
    store = PostgresHomePhysicalMemoryStore(lambda: next(connections))

    result = store.latest(user_id="tenant-b", object_name="KEYS", min_confidence=0.7)

    assert result is not None
    assert result.location == "desk"
    assert result.evidence_id == "frame-9"
    statement, params = statements[-1]
    assert "WHERE user_id = %s" in statement
    assert "LOWER(object_name) = LOWER(%s)" in statement
    assert "confidence >= %s" in statement
    assert params == ("tenant-b", "KEYS", 0.7)


def test_latest_returns_none_when_no_tenant_row_matches():
    statements = []
    connections = iter([FakeConnection(statements), FakeConnection(statements, [FakeResult(one=None)])])
    store = PostgresHomePhysicalMemoryStore(lambda: next(connections))

    assert store.latest(user_id="tenant-a", object_name="keys") is None


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        ("store_sighting", {"user_id": "", "sighting": _sighting()}),
        ("store_presence_event", {"user_id": "", "event": _departure()}),
        ("latest_presence_event", {"user_id": "", "kind": "home_departure"}),
        ("latest_presence_event", {"user_id": "tenant-a", "kind": "unknown"}),
        ("latest_presence_event", {"user_id": "tenant-a", "min_confidence": 1.1}),
        ("latest_presence_event", {"user_id": "tenant-a", "before": datetime(2026, 9, 22, 15, 0)}),
        ("latest", {"user_id": "", "object_name": "keys"}),
        ("latest", {"user_id": "tenant-a", "object_name": ""}),
        ("latest", {"user_id": "tenant-a", "object_name": "keys", "min_confidence": 1.1}),
    ],
)
def test_invalid_identity_or_confidence_fails_before_query(method, kwargs):
    statements = []
    store = PostgresHomePhysicalMemoryStore(lambda: FakeConnection(statements))
    schema_statement_count = len(statements)

    with pytest.raises(ValueError):
        getattr(store, method)(**kwargs)
    assert len(statements) == schema_statement_count
