"""Tenant-scoped Postgres persistence for Home Agent physical sightings."""

from __future__ import annotations

from app.db.account_erasure_fence import require_active_tenant

from datetime import datetime

from app.db.postgres_job_repository import ConnectionFactory
from app.services.home_agent import ObjectSighting
from app.services.home_agent.presence_events import HomePresenceEvent


def ensure_postgres_home_physical_memory_schema(connection_factory: ConnectionFactory) -> None:
    """Create the Home Agent physical-memory tables idempotently."""
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS home_presence_events (
                user_id TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('home_departure', 'home_arrival')),
                occurred_at TIMESTAMPTZ NOT NULL,
                confidence DOUBLE PRECISION NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
                source_id TEXT NOT NULL,
                PRIMARY KEY (user_id, evidence_id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_home_presence_events_lookup
            ON home_presence_events(user_id, kind, occurred_at DESC)
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
            require_active_tenant(conn, user_id=user_id)
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

    def store_presence_event(self, *, user_id: str, event: HomePresenceEvent) -> bool:
        """Persist an evidence-backed presence transition for exactly one tenant."""
        user_id = _required("user_id", user_id)
        with self._connect() as conn:
            require_active_tenant(conn, user_id=user_id)
            result = conn.execute(
                """
                INSERT INTO home_presence_events (
                    user_id, evidence_id, kind, occurred_at, confidence, source_id
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(user_id, evidence_id) DO NOTHING
                RETURNING evidence_id
                """,
                (user_id, event.evidence_id, event.kind, event.occurred_at_utc,
                 event.confidence, event.source_id),
            )
            return result.fetchone() is not None

    def latest_presence_event(
        self, *, user_id: str, kind: str = "home_departure", min_confidence: float = 0.5,
        before: datetime | None = None,
    ) -> HomePresenceEvent | None:
        """Return the newest qualified tenant-owned presence event, optionally before a bound."""
        user_id = _required("user_id", user_id)
        if kind not in ("home_departure", "home_arrival"):
            raise ValueError("unsupported presence event kind")
        _validate_confidence(min_confidence)
        if before is not None and (before.tzinfo is None or before.utcoffset() is None):
            raise ValueError("before must be timezone-aware")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT kind, occurred_at, confidence, source_id, evidence_id
                FROM home_presence_events
                WHERE user_id = %s AND kind = %s AND confidence >= %s
                  AND (%s IS NULL OR occurred_at < %s)
                ORDER BY occurred_at DESC, evidence_id DESC
                LIMIT 1
                """,
                (user_id, kind, min_confidence, before, before),
            ).fetchone()
        if row is None:
            return None
        return HomePresenceEvent(
            kind=row["kind"], occurred_at_utc=row["occurred_at"],
            confidence=float(row["confidence"]), source_id=row["source_id"],
            evidence_id=row["evidence_id"],
        )

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
        _validate_confidence(min_confidence)

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
        return _row_to_sighting(row) if row else None

    def history(
        self,
        *,
        user_id: str,
        object_name: str,
        min_confidence: float = 0.0,
        limit: int = 20,
    ) -> list[ObjectSighting]:
        """Return deterministic newest-first history for exactly one tenant."""
        user_id = _required("user_id", user_id)
        object_name = _required("object_name", object_name)
        _validate_confidence(min_confidence)
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT object_name, location, observed_at, confidence, source_id, evidence_id
                FROM home_object_sightings
                WHERE user_id = %s
                  AND LOWER(object_name) = LOWER(%s)
                  AND confidence >= %s
                ORDER BY observed_at DESC, evidence_id DESC
                LIMIT %s
                """,
                (user_id, object_name, min_confidence, limit),
            ).fetchall()
        return [_row_to_sighting(row) for row in rows]


def _row_to_sighting(row) -> ObjectSighting:
    return ObjectSighting(
        object_name=row["object_name"],
        location=row["location"],
        observed_at=datetime.fromisoformat(row["observed_at"]),
        confidence=float(row["confidence"]),
        source_id=row["source_id"],
        evidence_id=row["evidence_id"],
    )


def _validate_confidence(value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError("min_confidence must be between 0.0 and 1.0")


def _required(name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized
