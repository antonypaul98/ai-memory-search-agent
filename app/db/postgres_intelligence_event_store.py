"""Postgres persistence for Memory Intelligence events.

This bounded P-03 slice migrates only intelligence-event persistence. It keeps
runtime behavior tenant-scoped and deterministic while leaving service cutover
and SQLite migration to separately validated follow-up changes.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

ConnectionFactory = Callable[[], Any]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PostgresIntelligenceEventStore:
    """Exact-tenant durable storage for Memory Intelligence events."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self._connection_factory() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS intelligence_events (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    topic TEXT,
                    video_id TEXT,
                    query TEXT,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_intel_events_user_created ON intelligence_events(user_id, created_at DESC, id DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_intel_events_type ON intelligence_events(user_id, event_type, created_at DESC, id DESC)"
            )

    def record_event(
        self,
        *,
        user_id: str,
        event_type: str,
        topic: str | None = None,
        video_id: str | None = None,
        query: str | None = None,
    ) -> None:
        if not user_id:
            raise ValueError("user_id is required")
        if not event_type:
            raise ValueError("event_type is required")
        with self._connection_factory() as conn:
            conn.execute(
                """
                INSERT INTO intelligence_events (
                    user_id, event_type, topic, video_id, query, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (user_id, event_type, topic, video_id, query, _now()),
            )

    def recent_events(
        self, user_id: str, *, event_type: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        if not user_id:
            raise ValueError("user_id is required")
        bounded_limit = max(0, int(limit))
        with self._connection_factory() as conn:
            if event_type:
                rows = conn.execute(
                    """
                    SELECT id, user_id, event_type, topic, video_id, query, created_at
                    FROM intelligence_events
                    WHERE user_id = %s AND event_type = %s
                    ORDER BY created_at DESC, id DESC LIMIT %s
                    """,
                    (user_id, event_type, bounded_limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, user_id, event_type, topic, video_id, query, created_at
                    FROM intelligence_events
                    WHERE user_id = %s
                    ORDER BY created_at DESC, id DESC LIMIT %s
                    """,
                    (user_id, bounded_limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def save_dates(self, user_id: str) -> list[str]:
        if not user_id:
            raise ValueError("user_id is required")
        with self._connection_factory() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT CAST(created_at AT TIME ZONE 'UTC' AS DATE) AS d
                FROM intelligence_events
                WHERE user_id = %s AND event_type = 'save'
                ORDER BY d DESC
                """,
                (user_id,),
            ).fetchall()
        return [row["d"].isoformat() if hasattr(row["d"], "isoformat") else str(row["d"]) for row in rows if row["d"]]
