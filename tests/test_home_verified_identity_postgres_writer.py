"""Synthetic transactional SQL contract; no physical identity or camera claims."""
from dataclasses import replace

import pytest

from app.db.postgres_home_image_store import PostgresHomeImageStore
from app.services.home_agent.verified_identity_ingest import VerifiedInstanceProof


class Cursor:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class Connection:
    def __init__(self, statements, *, sighting=True, frame_source="camera-a",
                 source="camera-a", insert=True, fenced=False):
        self.statements = statements
        self.sighting = sighting
        self.frame_source = frame_source
        self.source = source
        self.insert = insert
        self.fenced = fenced

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.statements.append((normalized, params))
        if "FROM pg_class" in normalized:
            return Cursor({"exists": 1} if self.fenced else None)
        if "FROM account_erasure_fences" in normalized:
            return Cursor({"fenced": 1} if self.fenced else None)
        if "FROM home_object_sightings s" in normalized:
            return Cursor({"source_id": self.source,
                           "frame_source_id": self.frame_source}
                          if self.sighting else None)
        if "INSERT INTO home_verified_instance_associations" in normalized:
            return Cursor({"observation_id": "obs-a"} if self.insert else None)
        return Cursor()


def proof(**changes):
    return replace(VerifiedInstanceProof(
        user_id="house-a", observation_id="obs-a", source_id="camera-a",
        instance_id="keys-a", identity_evidence_id="proof-a",
        identity_confidence=0.97,
    ), **changes)


def store_for(**settings):
    statements = []
    store = PostgresHomeImageStore(lambda: Connection(statements, **settings))
    return store, statements


def test_schema_restricts_proof_to_single_sighting_and_erases_with_evidence():
    _, statements = store_for()
    sql = "\n".join(statement for statement, _ in statements)
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_home_verified_identity_proof_unique" in sql
    assert "ON home_verified_instance_associations(user_id, identity_evidence_id)" in sql
    assert "REFERENCES home_object_sightings(user_id, evidence_id) ON DELETE CASCADE" in sql


def test_trusted_writer_uses_erasure_fence_source_and_row_lock():
    store, statements = store_for()
    assert store.store_verified_instance_association(proof=proof()) is True
    sql = "\n".join(statement for statement, _ in statements)
    assert "pg_advisory_xact_lock_shared" in sql
    assert "FOR UPDATE OF s" in sql
    assert "JOIN home_image_observations i" in sql
    assert "JOIN home_image_evidence e" in sql
    assert "ON CONFLICT DO NOTHING" in sql
    sighting = next((statement, params) for statement, params in statements
                   if "FROM home_object_sightings s" in statement)
    assert sighting[1] == ("house-a", "obs-a")
    insert = next((statement, params) for statement, params in statements
                  if "INSERT INTO home_verified_instance_associations" in statement)
    assert insert[1] == ("house-a", "obs-a", "keys-a", "proof-a", 0.97)


@pytest.mark.parametrize("settings", [
    {"sighting": False}, {"source": "camera-b"},
    {"frame_source": "camera-b"},
])
def test_missing_or_mismatched_retained_source_fails_closed(settings):
    store, statements = store_for(**settings)
    assert store.store_verified_instance_association(proof=proof()) is False
    assert not any("INSERT INTO home_verified_instance_associations" in sql
                   for sql, _ in statements)


def test_duplicate_observation_or_proof_collision_is_non_mutating():
    store, statements = store_for(insert=False)
    assert store.store_verified_instance_association(proof=proof()) is False
    assert any("ON CONFLICT DO NOTHING" in sql for sql, _ in statements)


def test_erased_tenant_is_fenced_before_observation_lookup():
    store, statements = store_for(fenced=True)
    with pytest.raises(PermissionError):
        store.store_verified_instance_association(proof=proof())
    assert not any("FROM home_object_sightings s" in sql for sql, _ in statements)


@pytest.mark.parametrize("bad", [
    "client-asserted", {"instance_id": "keys-a"}, None,
])
def test_untrusted_or_malformed_proof_type_rejected_before_sql(bad):
    store, statements = store_for()
    before = len(statements)
    with pytest.raises(TypeError):
        store.store_verified_instance_association(proof=bad)
    assert len(statements) == before


def test_sighting_id_cannot_double_as_identity_proof():
    store, statements = store_for()
    before = len(statements)
    with pytest.raises(ValueError):
        store.store_verified_instance_association(
            proof=proof(identity_evidence_id="obs-a"))
    assert len(statements) == before


def test_low_confidence_is_not_written_even_if_called_directly():
    store, statements = store_for()
    before = len(statements)
    assert not store.store_verified_instance_association(
        proof=proof(identity_confidence=0.89))
    assert len(statements) == before
