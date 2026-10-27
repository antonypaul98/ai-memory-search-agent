"""Synthetic transactional SQL contract; no physical identity or camera claims."""
from dataclasses import replace

import pytest

from app.db.postgres_home_image_store import PostgresHomeImageStore
from app.services.home_agent.verified_identity_ingest import VerifiedInstanceProof


class Cursor:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows if rows is not None else []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, statements, *, sighting=True, frame_source="camera-a",
                 source="camera-a", insert=True, fenced=False,
                 consent=True, erased=1):
        self.statements = statements
        self.sighting = sighting
        self.frame_source = frame_source
        self.source = source
        self.insert = insert
        self.fenced = fenced
        self.consent = consent
        self.erased = erased

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
        if "FROM home_instance_identity_consents" in normalized:
            return Cursor({"granted_at": "server-grant-time"} if self.consent else None)
        if "DELETE FROM home_verified_instance_associations a" in normalized:
            return Cursor(rows=[{"observation_id": f"obs-{i}"} for i in range(self.erased)])
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
    assert "CREATE TABLE IF NOT EXISTS home_instance_identity_consents" in sql
    assert "PRIMARY KEY (user_id, source_id)" in sql
    assert "CHECK (expires_at > granted_at)" in sql


def test_trusted_writer_uses_erasure_fence_source_and_row_lock():
    store, statements = store_for()
    assert store.store_verified_instance_association(proof=proof()) is True
    sql = "\n".join(statement for statement, _ in statements)
    assert "pg_advisory_xact_lock_shared" in sql
    assert "FOR UPDATE OF s" in sql
    assert "FROM home_instance_identity_consents" in sql
    assert "FOR SHARE" in sql
    assert "revoked_at IS NULL" in sql
    assert "expires_at > CURRENT_TIMESTAMP" in sql
    consent = next((statement, params) for statement, params in statements
                   if "FROM home_instance_identity_consents" in statement)
    assert consent[1] == ("house-a", "camera-a")
    assert sql.index("FROM home_instance_identity_consents") < sql.index("FROM home_object_sightings s")
    assert "JOIN home_image_observations i" in sql
    assert "JOIN home_image_evidence e" in sql
    assert "SELECT granted_at FROM home_instance_identity_consents" in sql
    assert "e.observed_at >= %s" in sql
    assert "ON CONFLICT DO NOTHING" in sql
    sighting = next((statement, params) for statement, params in statements
                   if "FROM home_object_sightings s" in statement)
    assert sighting[1] == ("house-a", "obs-a", "server-grant-time")
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


def test_absent_revoked_or_expired_server_grant_fails_closed_before_sighting():
    # The SQL time predicate handles expiry; the fake models no qualifying row.
    store, statements = store_for(consent=False)
    assert store.store_verified_instance_association(proof=proof()) is False
    assert any("revoked_at IS NULL" in sql and "FOR SHARE" in sql
               for sql, _ in statements)
    assert not any("FROM home_object_sightings s" in sql for sql, _ in statements)
    assert not any("INSERT INTO home_verified_instance_associations" in sql
                   for sql, _ in statements)


def test_revoke_serializes_with_writers_and_erases_only_source_associations():
    store, statements = store_for(erased=2)
    assert store.revoke_instance_identity_consent(
        user_id="house-a", source_id="camera-a") == 2
    sql = "\n".join(statement for statement, _ in statements)
    assert "pg_advisory_xact_lock_shared" in sql
    assert "FOR UPDATE" in sql
    assert "SET revoked_at = CURRENT_TIMESTAMP" in sql
    assert "DELETE FROM home_verified_instance_associations a" in sql
    assert "USING home_object_sightings s" in sql
    assert "a.user_id = s.user_id" in sql
    assert "s.source_id = %s" in sql
    scoped = [(statement, params) for statement, params in statements
              if "FROM home_instance_identity_consents" in statement
              or "UPDATE home_instance_identity_consents" in statement
              or "DELETE FROM home_verified_instance_associations a" in statement]
    assert len(scoped) == 3
    assert all(params == ("house-a", "camera-a") for _, params in scoped)
    assert sql.index("FOR UPDATE") < sql.index("DELETE FROM home_verified_instance_associations a")


def test_revocation_is_idempotent_when_no_identity_links_exist():
    store, statements = store_for(consent=False, erased=0)
    assert store.revoke_instance_identity_consent(
        user_id="house-a", source_id="camera-a") == 0
    assert not any("INSERT INTO home_verified_instance_associations" in sql
                   for sql, _ in statements)


def test_erased_tenant_cannot_revoke_or_recreate_identity_links():
    store, statements = store_for(fenced=True)
    with pytest.raises(PermissionError):
        store.revoke_instance_identity_consent(
            user_id="house-a", source_id="camera-a")
    assert not any("UPDATE home_instance_identity_consents" in sql
                   for sql, _ in statements)
