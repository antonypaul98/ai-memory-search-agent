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
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_home_verified_instance_associations_tenant
                ON home_verified_instance_associations(user_id, instance_id)
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
