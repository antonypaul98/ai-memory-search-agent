"""Atomic image evidence + canonical class memory in the existing Postgres database.

Extends the existing sightings table. Class IDs group observations for retrieval;
they do not establish that two detections are the same physical instance.
"""
from __future__ import annotations

from app.db.account_erasure_fence import require_active_tenant

import json
from datetime import datetime
from hashlib import sha256
from math import isfinite

from app.services.home_agent.instance_location import InstanceObservation
from app.services.home_agent.verified_identity_ingest import (
    MIN_IDENTITY_CONFIDENCE, VerifiedInstanceProof,
)

from app.db.postgres_home_physical_memory_store import PostgresHomePhysicalMemoryStore, _required
from app.services.home_agent.image_ingest import ImageObservationBatch, canonical_id


class PostgresHomeImageStore(PostgresHomePhysicalMemoryStore):
    def __init__(self, connection_factory):
        super().__init__(connection_factory)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS home_image_evidence (
                    user_id TEXT NOT NULL, frame_id TEXT NOT NULL,
                    image_bytes BYTEA NOT NULL, image_sha256 TEXT NOT NULL,
                    source_id TEXT NOT NULL, location TEXT NOT NULL,
                    observed_at TIMESTAMPTZ NOT NULL, detector_id TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(user_id, frame_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS home_physical_objects (
                    user_id TEXT NOT NULL, object_id TEXT NOT NULL,
                    object_class TEXT NOT NULL,
                    identity_kind TEXT NOT NULL DEFAULT 'class',
                    PRIMARY KEY(user_id, object_id), UNIQUE(user_id, object_class)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS home_image_observations (
                    user_id TEXT NOT NULL, observation_id TEXT NOT NULL,
                    object_id TEXT NOT NULL, frame_id TEXT NOT NULL, box_json TEXT NOT NULL,
                    PRIMARY KEY(user_id, observation_id),
                    FOREIGN KEY(user_id, observation_id)
                        REFERENCES home_object_sightings(user_id, evidence_id) ON DELETE CASCADE,
                    FOREIGN KEY(user_id, object_id)
                        REFERENCES home_physical_objects(user_id, object_id),
                    FOREIGN KEY(user_id, frame_id)
                        REFERENCES home_image_evidence(user_id, frame_id)
                )
            """)

            # Class-only image detections cannot populate this table. A future
            # consented identity verifier must supply independently checked proof.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS home_verified_instance_associations (
                    user_id TEXT NOT NULL,
                    observation_id TEXT NOT NULL,
                    instance_id TEXT NOT NULL CHECK (length(btrim(instance_id)) > 0),
                    identity_evidence_id TEXT NOT NULL CHECK (length(btrim(identity_evidence_id)) > 0),
                    identity_confidence DOUBLE PRECISION NOT NULL
                        CHECK (identity_confidence >= 0 AND identity_confidence <= 1),
                    PRIMARY KEY (user_id, observation_id),
                    FOREIGN KEY (user_id, observation_id)
                        REFERENCES home_object_sightings(user_id, evidence_id) ON DELETE CASCADE
                )
            """)
            # An internal verifier proof is insufficient by itself: a current
            # server-managed grant must exist when the transaction commits.
            # Revocation locks the same row and removes prior associations.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS home_instance_identity_consents (
                    user_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    granted_at TIMESTAMPTZ NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    revoked_at TIMESTAMPTZ,
                    PRIMARY KEY (user_id, source_id),
                    CHECK (expires_at > granted_at)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_home_verified_instance_associations_tenant
                ON home_verified_instance_associations(user_id, instance_id)
            """)

            # A verifier proof is evidence for one sighting, not a reusable
            # physical-instance label. Enforce this across concurrent writers.
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_home_verified_identity_proof_unique
                ON home_verified_instance_associations(user_id, identity_evidence_id)
            """)

    def store_image_batch(self, batch: ImageObservationBatch) -> dict:
        _required("user_id", batch.user_id)
        if sha256(batch.image_bytes).hexdigest() != batch.image_sha256:
            raise ValueError("evidence hash mismatch")
        inserted = 0
        # No detections means no private frame retention.
        if not batch.detections:
            return {"frame_id": None, "stored_observations": 0, "retained_bytes": 0}
        with self._connect() as conn:
            require_active_tenant(conn, user_id=batch.user_id)
            frame = conn.execute("""
                INSERT INTO home_image_evidence
                    (user_id, frame_id, image_bytes, image_sha256, source_id, location, observed_at, detector_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(user_id, frame_id) DO NOTHING RETURNING frame_id
            """, (batch.user_id, batch.frame_id, batch.image_bytes, batch.image_sha256,
                  batch.source_id, batch.location, batch.observed_at, batch.detector_id)).fetchone()
            # The first successfully committed run is authoritative on retry,
            # including if a newer detector would produce different outputs.
            if frame is None:
                return {"frame_id": batch.frame_id, "stored_observations": 0, "retained_bytes": 0}
            for detection in batch.detections:
                object_id = canonical_id("object", batch.user_id, detection.object_class)
                observation_id = canonical_id("observation", batch.frame_id, detection.object_class,
                                              json.dumps(detection.box))
                conn.execute("""
                    INSERT INTO home_physical_objects(user_id, object_id, object_class)
                    VALUES (%s,%s,%s) ON CONFLICT(user_id, object_id) DO NOTHING
                """, (batch.user_id, object_id, detection.object_class))
                row = conn.execute("""
                    INSERT INTO home_object_sightings
                        (user_id,evidence_id,object_name,location,observed_at,confidence,source_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(user_id,evidence_id) DO NOTHING RETURNING evidence_id
                """, (batch.user_id, observation_id, detection.object_class, batch.location,
                      batch.observed_at.isoformat(), detection.confidence, batch.source_id)).fetchone()
                if row is not None:
                    inserted += 1
                    conn.execute("""
                        INSERT INTO home_image_observations
                            (user_id, observation_id, object_id, frame_id, box_json)
                        VALUES (%s,%s,%s,%s,%s)
                    """, (batch.user_id, observation_id, object_id, batch.frame_id, json.dumps(detection.box)))
        return {"frame_id": batch.frame_id, "stored_observations": inserted,
                "retained_bytes": len(batch.image_bytes)}

    def describe_observation(self, *, user_id: str, observation_id: str) -> dict | None:
        _required("user_id", user_id)
        with self._connect() as conn:
            row = conn.execute("""
                SELECT o.observation_id, o.object_id, o.frame_id, o.box_json,
                       p.object_class, p.identity_kind, e.image_sha256, e.detector_id
                FROM home_image_observations o
                JOIN home_physical_objects p ON p.user_id=o.user_id AND p.object_id=o.object_id
                JOIN home_image_evidence e ON e.user_id=o.user_id AND e.frame_id=o.frame_id
                WHERE o.user_id=%s AND o.observation_id=%s
            """, (user_id, observation_id)).fetchone()
        return dict(row) if row else None

    def get_image(self, *, user_id: str, frame_id: str) -> bytes | None:
        _required("user_id", user_id)
        with self._connect() as conn:
            row = conn.execute("SELECT image_bytes FROM home_image_evidence WHERE user_id=%s AND frame_id=%s",
                               (user_id, frame_id)).fetchone()
        return bytes(row["image_bytes"]) if row else None

    def delete_image(self, *, user_id: str, frame_id: str) -> bool:
        _required("user_id", user_id)
        with self._connect() as conn:
            # Serialize deletion with retry against this exact tenant's frame.
            frame = conn.execute("SELECT frame_id FROM home_image_evidence WHERE user_id=%s AND frame_id=%s FOR UPDATE",
                                 (user_id, frame_id)).fetchone()
            if frame is None:
                return False
            conn.execute("""DELETE FROM home_object_sightings
                WHERE user_id=%s AND evidence_id IN
                    (SELECT observation_id FROM home_image_observations WHERE user_id=%s AND frame_id=%s)
            """, (user_id, user_id, frame_id))
            conn.execute("DELETE FROM home_image_evidence WHERE user_id=%s AND frame_id=%s", (user_id, frame_id))
            conn.execute("""DELETE FROM home_physical_objects p WHERE p.user_id=%s
                AND NOT EXISTS (SELECT 1 FROM home_image_observations o
                    WHERE o.user_id=p.user_id AND o.object_id=p.object_id)""", (user_id,))
            return True

    def store_verified_instance_association(self, *, proof: VerifiedInstanceProof) -> bool:
        """Persist one independently verified, consent-gated sighting association.

        Internal-only storage boundary. The caller must be the trusted
        VerifiedInstanceIngestService; this method cannot itself verify physical
        identity or issue/revoke consent. A proof ID is single-use per tenant,
        even when two observations claim the same instance.
        """
        if not isinstance(proof, VerifiedInstanceProof):
            raise TypeError("trusted verified instance proof required")
        if proof.identity_evidence_id == proof.observation_id:
            raise ValueError("identity evidence must be independent of the sighting")
        if proof.identity_confidence < MIN_IDENTITY_CONFIDENCE:
            return False
        with self._connect() as conn:
            # Shared erasure lock is held through transaction commit.
            require_active_tenant(conn, user_id=proof.user_id)
            # This lock serializes identity writes with consent revocation.
            # Consent must be provisioned by a separately authorized server
            # component; a caller-supplied consent dataclass is not authority.
            active_consent = conn.execute("""
                SELECT granted_at FROM home_instance_identity_consents
                WHERE user_id = %s AND source_id = %s
                  AND revoked_at IS NULL
                  AND granted_at <= CURRENT_TIMESTAMP
                  AND expires_at > CURRENT_TIMESTAMP
                FOR SHARE
            """, (proof.user_id, proof.source_id)).fetchone()
            if active_consent is None:
                return False
            # Lock the exact tenant-owned source sighting against deletion.
            # Only retained image observations captured after this server grant
            # may be linked; re-grant cannot retroactively identify old frames.
            # The server's retention timestamp also must postdate the grant:
            # a client-supplied future observed_at cannot backdate consent.
            sighting = conn.execute("""
                SELECT s.source_id, e.source_id AS frame_source_id
                FROM home_object_sightings s
                JOIN home_image_observations i
                  ON i.user_id = s.user_id AND i.observation_id = s.evidence_id
                JOIN home_image_evidence e
                  ON e.user_id = i.user_id AND e.frame_id = i.frame_id
                WHERE s.user_id = %s AND s.evidence_id = %s
                  AND e.observed_at >= %s
                  AND e.created_at >= %s
                FOR UPDATE OF s
            """, (proof.user_id, proof.observation_id,
                  active_consent["granted_at"], active_consent["granted_at"])).fetchone()
            if (sighting is None or sighting["source_id"] != proof.source_id
                    or sighting["frame_source_id"] != proof.source_id):
                return False
            # Unique tenant/proof constraint and tenant/observation PK enforce
            # single-use provenance and idempotence under concurrent writes.
            inserted = conn.execute("""
                INSERT INTO home_verified_instance_associations
                    (user_id, observation_id, instance_id,
                     identity_evidence_id, identity_confidence)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING observation_id
            """, (proof.user_id, proof.observation_id, proof.instance_id,
                  proof.identity_evidence_id, proof.identity_confidence)).fetchone()
            return inserted is not None

    def grant_instance_identity_consent(
        self, *, user_id: str, source_id: str, ttl_seconds: int = 300,
    ) -> datetime:
        """Issue a time-bounded, tenant-scoped server grant after caller auth.

        Only an authenticated server route may invoke this method. The database
        computes grant/expiry times; clients cannot backdate or extend them.
        Re-grant after explicit revocation never restores erased associations.
        """
        user_id = _required("user_id", user_id)
        source_id = _required("source_id", source_id)
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 3600:
            raise ValueError("ttl_seconds must be between 1 and 3600")
        with self._connect() as conn:
            require_active_tenant(conn, user_id=user_id)
            # The PK upsert serializes concurrent grant/revoke transactions.
            # Do not derive consent from a capture session or client timestamp.
            row = conn.execute("""
                INSERT INTO home_instance_identity_consents
                    (user_id, source_id, granted_at, expires_at, revoked_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP,
                        CURRENT_TIMESTAMP + (%s * INTERVAL '1 second'), NULL)
                ON CONFLICT (user_id, source_id) DO UPDATE
                SET granted_at = EXCLUDED.granted_at,
                    expires_at = EXCLUDED.expires_at,
                    revoked_at = NULL
                RETURNING expires_at
            """, (user_id, source_id, ttl_seconds)).fetchone()
            return row["expires_at"]

    def revoke_instance_identity_consent(self, *, user_id: str, source_id: str) -> int:
        """Revoke a source grant and erase its identity links atomically.

        Internal-only; the caller must independently authenticate and authorize
        the tenant's consent decision. Ordinary class sightings are retained.
        Writers hold a shared lock on the grant, so a completed revocation
        cannot race with a later association write.
        """
        user_id = _required("user_id", user_id)
        source_id = _required("source_id", source_id)
        with self._connect() as conn:
            require_active_tenant(conn, user_id=user_id)
            conn.execute("""
                SELECT 1 FROM home_instance_identity_consents
                WHERE user_id = %s AND source_id = %s FOR UPDATE
            """, (user_id, source_id)).fetchone()
            conn.execute("""
                UPDATE home_instance_identity_consents
                SET revoked_at = CURRENT_TIMESTAMP
                WHERE user_id = %s AND source_id = %s AND revoked_at IS NULL
            """, (user_id, source_id))
            erased = conn.execute("""
                DELETE FROM home_verified_instance_associations a
                USING home_object_sightings s
                WHERE a.user_id = s.user_id
                  AND a.observation_id = s.evidence_id
                  AND a.user_id = %s AND s.source_id = %s
                RETURNING a.observation_id
            """, (user_id, source_id)).fetchall()
            return len(erased)

    def verified_instance_observations(
        self, *, user_id: str, object_name: str,
        min_confidence: float = 0.9, limit: int = 20,
    ) -> list[InstanceObservation]:
        """Read identity-evidenced sightings only, never class-level object IDs.

        No identity association writer is exposed in this checkpoint. The
        reader stays empty until a trusted, consented producer is implemented.
        """
        user_id = _required("user_id", user_id)
        object_name = _required("object_name", object_name)
        if (isinstance(min_confidence, bool)
                or not isinstance(min_confidence, (int, float))
                or not isfinite(min_confidence)
                or not 0 <= min_confidence <= 1):
            raise ValueError("min_confidence must be finite and between 0 and 1")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

        with self._connect() as conn:
            rows = conn.execute("""
                SELECT s.user_id, s.object_name, s.location, s.observed_at,
                       s.source_id, s.evidence_id, a.instance_id,
                       a.identity_evidence_id, a.identity_confidence
                FROM home_verified_instance_associations a
                JOIN home_object_sightings s
                  ON s.user_id = a.user_id AND s.evidence_id = a.observation_id
                WHERE a.user_id = %s AND LOWER(s.object_name) = LOWER(%s)
                  AND s.confidence >= %s AND a.identity_confidence >= %s
                ORDER BY s.observed_at DESC, s.evidence_id DESC
                LIMIT %s
            """, (user_id, object_name, min_confidence, min_confidence, limit)).fetchall()

        try:
            return [
                InstanceObservation(
                    user_id=row["user_id"], object_class=row["object_name"],
                    location=row["location"],
                    observed_at=(datetime.fromisoformat(row["observed_at"])
                                 if isinstance(row["observed_at"], str)
                                 else row["observed_at"]),
                    source_id=row["source_id"], evidence_id=row["evidence_id"],
                    instance_id=row["instance_id"],
                    identity_evidence_id=row["identity_evidence_id"],
                    identity_confidence=float(row["identity_confidence"]),
                )
                for row in rows
            ]
        except (KeyError, TypeError, ValueError, OverflowError):
            # Reject the entire malformed result rather than exposing a
            # partially trusted identity chain.
            return []
