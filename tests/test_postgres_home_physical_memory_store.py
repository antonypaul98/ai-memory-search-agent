from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.postgres_home_physical_memory_store import PostgresHomePhysicalMemoryStore
from app.services.home_agent import ObjectSighting


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


def test_schema_keys_evidence_by_tenant():
    statements = []
    PostgresHomePhysicalMemoryStore(lambda: FakeConnection(statements))

    sql = "\n".join(statement for statement, _ in statements)
    assert "PRIMARY KEY (user_id, evidence_id)" in sql
    assert "idx_home_object_sightings_lookup" in sql
    assert "ON home_object_sightings(user_id, object_name, observed_at DESC)" in sql


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
