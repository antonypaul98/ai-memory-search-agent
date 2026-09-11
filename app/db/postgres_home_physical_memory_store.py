"""Tenant-scoped Postgres persistence for Home Agent physical sightings."""

from __future__ import annotations

from datetime import datetime

from app.db.postgres_job_repository import ConnectionFactory
from app.services.home_agent import ObjectSighting


def ensure_postgres_home_physical_memory_schema(connection_factory: ConnectionFactory) -> None:
    """Create the Home Agent physical-memory table idempotently."""
    with connection_factory() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS home_object_sightings (
                user_id TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                object_name TEXT NOT NULL,
                location TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                confidence DOUBLE PRECISION NOT NULL,
                source_id TEXT NOT NULL,
                PRIMARY KEY (user_id, evidence_id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_home_object_sightings_lookup
            ON home_object_sightings(user_id, object_name, observed_at DESC)
            """
        )


class PostgresHomePhysicalMemoryStore:
    """Persist and retrieve Home Agent sightings within an exact tenant boundary."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connect = connection_factory
        ensure_postgres_home_physical_memory_schema(connection_factory)

    def store_sighting(self, *, user_id: str, sighting: ObjectSighting) -> bool:
        """Store a sighting once; duplicate evidence for the same tenant is ignored."""
        user_id = _required("user_id", user_id)
        with self._connect() as conn:
            result = conn.execute(
                """
                INSERT INTO home_object_sightings (
                    user_id, evidence_id, object_name, location,
                    observed_at, confidence, source_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(user_id, evidence_id) DO NOTHING
                RETURNING evidence_id
                """,
                (
                    user_id,
                    sighting.evidence_id,
                    sighting.object_name,
                    sighting.location,
                    sighting.observed_at_utc.isoformat(),
                    sighting.confidence,
                    sighting.source_id,
                ),
            )
            return result.fetchone() is not None

    def latest(
        self,
        *,
        user_id: str,
        object_name: str,
        min_confidence: float = 0.0,
    ) -> ObjectSighting | None:
        """Return the newest qualifying sighting for exactly one tenant."""
        user_id = _required("user_id", user_id)
        object_name = _required("object_name", object_name)
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0.0 and 1.0")

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT object_name, location, observed_at, confidence, source_id, evidence_id
                FROM home_object_sightings
                WHERE user_id = %s
                  AND LOWER(object_name) = LOWER(%s)
                  AND confidence >= %s
                ORDER BY observed_at DESC, evidence_id DESC
                LIMIT 1
                """,
                (user_id, object_name, min_confidence),
            ).fetchone()
        if not row:
            return None
        return ObjectSighting(
            object_name=row["object_name"],
            location=row["location"],
            observed_at=datetime.fromisoformat(row["observed_at"]),
            confidence=float(row["confidence"]),
            source_id=row["source_id"],
            evidence_id=row["evidence_id"],
        )


def _required(name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized
