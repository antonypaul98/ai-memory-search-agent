"""Atomic image evidence + canonical class memory in the existing Postgres database.

Extends the existing sightings table. Class IDs group observations for retrieval;
they do not establish that two detections are the same physical instance.
"""
from __future__ import annotations

from app.db.account_erasure_fence import require_active_tenant

import json
from hashlib import sha256

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
