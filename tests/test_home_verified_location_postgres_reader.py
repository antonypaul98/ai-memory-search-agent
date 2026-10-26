"""Synthetic SQL-contract checks; no camera or real biometric input."""
from datetime import datetime, timedelta, timezone

import pytest

from app.db.postgres_home_image_store import PostgresHomeImageStore
from app.services.home_agent.query_service import HomeAgentQueryService

BASE = datetime(2026, 10, 25, 18, 0, tzinfo=timezone.utc)


class Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, statements, rows):
        self.statements, self.rows = statements, rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.statements.append((sql, params))
        return Rows(self.rows if "FROM home_verified_instance_associations a" in sql else [])


def store_for(rows):
    statements = []
    store = PostgresHomeImageStore(lambda: Connection(statements, rows))
    return store, statements


def sighting(instance, location, seconds, *, tenant="house-a", confidence=0.99):
    return {
        "user_id": tenant, "object_name": "keys", "location": location,
        "observed_at": (BASE + timedelta(seconds=seconds)).isoformat(),
        "source_id": "consented-camera", "evidence_id": f"frame-{instance}-{seconds}",
        "instance_id": instance,
        "identity_evidence_id": f"verified-match-{tenant}-{instance}-{seconds}",
        "identity_confidence": confidence,
    }


def test_verified_schema_is_separate_and_cascades_evidence_deletion():
    _, statements = store_for([])
    sql = "\n".join(statement for statement, _ in statements)
    assert "CREATE TABLE IF NOT EXISTS home_verified_instance_associations" in sql
    assert "PRIMARY KEY (user_id, observation_id)" in sql
    assert "REFERENCES home_object_sightings(user_id, evidence_id) ON DELETE CASCADE" in sql


def test_verified_reader_preserves_provenance_and_tenant_sql_scope():
    store, statements = store_for([
        sighting("keys-1", "desk", 0), sighting("keys-1", "kitchen", 30),
    ])
    changes = HomeAgentQueryService(store).observed_location_changes(
        user_id="house-a", object_name="keys", min_confidence=0.9, limit=8,
    )
    assert len(changes) == 1
    assert (changes[0].from_location, changes[0].to_location) == ("desk", "kitchen")
    assert (changes[0].from_evidence_id, changes[0].to_evidence_id) == (
        "frame-keys-1-0", "frame-keys-1-30",
    )
    sql, params = statements[-1]
    assert "JOIN home_object_sightings s ON s.user_id = a.user_id" in sql
    assert "WHERE a.user_id = %s" in sql
    assert "s.confidence >= %s AND a.identity_confidence >= %s" in sql
    assert params == ("house-a", "keys", 0.9, 0.9, 8)


def test_two_identical_objects_do_not_create_a_false_relocation():
    store, _ = store_for([
        sighting("keys-1", "desk", 0), sighting("keys-2", "kitchen", 30),
    ])
    assert HomeAgentQueryService(store).observed_location_changes(
        user_id="house-a", object_name="keys",
    ) == []


def test_class_only_records_have_no_verified_associations():
    store, _ = store_for([])
    assert store.verified_instance_observations(user_id="house-a", object_name="keys") == []
    assert HomeAgentQueryService(store).observed_location_changes(
        user_id="house-a", object_name="keys",
    ) == []


def test_malformed_or_cross_tenant_rows_fail_closed():
    for rows in (
        [sighting("keys-1", "desk", 0), sighting("keys-1", "kitchen", 30, tenant="house-b")],
        [sighting("keys-1", "desk", 0),
         dict(sighting("keys-1", "kitchen", 30), identity_confidence="bad")],
    ):
        store, _ = store_for(rows)
        assert HomeAgentQueryService(store).observed_location_changes(
            user_id="house-a", object_name="keys",
        ) == []


@pytest.mark.parametrize("kwargs", [
    {"user_id": "", "object_name": "keys"},
    {"user_id": "house-a", "object_name": ""},
    {"user_id": "house-a", "object_name": "keys", "min_confidence": float("nan")},
    {"user_id": "house-a", "object_name": "keys", "min_confidence": True},
    {"user_id": "house-a", "object_name": "keys", "limit": True},
    {"user_id": "house-a", "object_name": "keys", "limit": 101},
])
def test_invalid_query_parameters_fail_before_sql(kwargs):
    store, statements = store_for([])
    before = len(statements)
    with pytest.raises(ValueError):
        store.verified_instance_observations(**kwargs)
    assert len(statements) == before
