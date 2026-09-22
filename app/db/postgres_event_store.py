"""Postgres persistence for tenant-scoped domain events and webhook subscriptions."""

from __future__ import annotations

from app.db.account_erasure_fence import require_active_tenant

from typing import Any

from app.db.postgres_job_repository import ConnectionFactory


class PostgresEventStore:
    """Durable event/audit persistence selected by the production memory backend."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory
        with connection_factory() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_events (
                    id BIGSERIAL PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    aggregate_type TEXT NOT NULL DEFAULT '',
                    aggregate_id TEXT NOT NULL DEFAULT '',
                    actor TEXT NOT NULL DEFAULT 'system',
                    request_id TEXT,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_events_user_id "
                "ON memory_events(user_id, id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_events_user_type_id "
                "ON memory_events(user_id, event_type, id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_events_user_request_id "
                "ON memory_events(user_id, request_id, id)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS webhook_subscriptions (
                    subscription_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL DEFAULT '*',
                    url TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_webhook_subscriptions_user "
                "ON webhook_subscriptions(user_id, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_webhook_subscriptions_delivery "
                "ON webhook_subscriptions(user_id, active, event_type)"
            )

    def create_subscription(
        self, *, subscription_id: str, user_id: str, event_type: str, url: str,
        created_at: str,
    ) -> None:
        with self._connection_factory() as conn:
            require_active_tenant(conn, user_id=user_id)
            conn.execute(
                """
                INSERT INTO webhook_subscriptions (
                    subscription_id, user_id, event_type, url, active, created_at
                ) VALUES (%s, %s, %s, %s, 1, %s)
                """,
                (subscription_id, user_id, event_type, url, created_at),
            )

    def list_subscriptions(self, *, user_id: str) -> list[dict[str, Any]]:
        with self._connection_factory() as conn:
            rows = conn.execute(
                """
                SELECT subscription_id, event_type, url, active, created_at
                FROM webhook_subscriptions
                WHERE user_id = %s
                ORDER BY created_at ASC, subscription_id ASC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_subscription(self, *, user_id: str, subscription_id: str) -> bool:
        with self._connection_factory() as conn:
            cursor = conn.execute(
                "DELETE FROM webhook_subscriptions "
                "WHERE user_id = %s AND subscription_id = %s",
                (user_id, subscription_id),
            )
        return cursor.rowcount > 0

    def insert_event(
        self, *, event_id: str, user_id: str, event_type: str,
        aggregate_type: str, aggregate_id: str, actor: str,
        request_id: str | None, payload_json: str, created_at: str,
    ) -> None:
        with self._connection_factory() as conn:
            require_active_tenant(conn, user_id=user_id)
            conn.execute(
                """
                INSERT INTO memory_events (
                    event_id, user_id, event_type, aggregate_type, aggregate_id,
                    actor, request_id, payload_json, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    event_id, user_id, event_type, aggregate_type, aggregate_id,
                    actor, request_id, payload_json, created_at,
                ),
            )

    def webhook_urls(self, *, user_id: str, event_type: str) -> list[str]:
        with self._connection_factory() as conn:
            rows = conn.execute(
                """
                SELECT url
                FROM webhook_subscriptions
                WHERE user_id = %s AND active = 1 AND event_type IN ('*', %s)
                ORDER BY created_at ASC, subscription_id ASC
                """,
                (user_id, event_type),
            ).fetchall()
        return [str(row["url"]) for row in rows]

    def list_events(
        self, *, user_id: str, event_type: str | None = None,
        after_id: int | None = None, request_id: str | None = None,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], int | None]:
        clauses = ["user_id = %s"]
        params: list[Any] = [user_id]
        if event_type:
            clauses.append("event_type = %s")
            params.append(event_type)
        if request_id:
            clauses.append("request_id = %s")
            params.append(request_id)
        if after_id is not None:
            clauses.append("id > %s")
            params.append(after_id)
        params.append(limit)
        with self._connection_factory() as conn:
            rows = conn.execute(
                f"""
                SELECT id, event_id, user_id, event_type, aggregate_type,
                       aggregate_id, actor, request_id, payload_json, created_at
                FROM memory_events
                WHERE {' AND '.join(clauses)}
                ORDER BY id ASC
                LIMIT %s
                """,
                params,
            ).fetchall()
        result = [dict(row) for row in rows]
        return result, (int(rows[-1]["id"]) if rows else after_id)

    def metrics(self, *, user_id: str) -> dict[str, int]:
        with self._connection_factory() as conn:
            rows = conn.execute(
                """
                SELECT event_type, COUNT(*) AS event_count
                FROM memory_events
                WHERE user_id = %s
                GROUP BY event_type
                ORDER BY event_type ASC
                """,
                (user_id,),
            ).fetchall()
        return {str(row["event_type"]): int(row["event_count"]) for row in rows}

    def export_user_data(self, *, user_id: str) -> dict[str, list[dict[str, Any]]]:
        """Export exact-tenant activity and non-secret subscription metadata.

        No LIMIT: privacy export must not inherit the interactive event page cap.
        URLs are deliberately excluded because they can carry delivery credentials.
        """
        self._require_privacy_user(user_id)
        with self._connection_factory() as conn:
            # Both collections describe the same database snapshot.
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            events = conn.execute(
                """SELECT id, event_id, user_id, event_type, aggregate_type,
                          aggregate_id, actor, request_id, payload_json, created_at
                   FROM memory_events WHERE user_id = %s ORDER BY id ASC""",
                (user_id,),
            ).fetchall()
            subscriptions = conn.execute(
                """SELECT subscription_id, user_id, event_type, active, created_at
                   FROM webhook_subscriptions WHERE user_id = %s
                   ORDER BY created_at ASC, subscription_id ASC""",
                (user_id,),
            ).fetchall()
        return {"events": [dict(row) for row in events],
                "subscriptions": [dict(row) for row in subscriptions]}

    def delete_user_data(self, *, user_id: str) -> dict[str, int]:
        """Erase subscriptions and events atomically for one exact tenant.

        Already-dispatched deliveries and concurrent producers require the separate
        account write barrier; this transaction does not claim to cancel them.
        """
        self._require_privacy_user(user_id)
        with self._connection_factory() as conn:
            subscriptions = conn.execute(
                "DELETE FROM webhook_subscriptions WHERE user_id = %s", (user_id,)
            ).rowcount
            events = conn.execute(
                "DELETE FROM memory_events WHERE user_id = %s", (user_id,)
            ).rowcount
        return {"subscriptions": int(subscriptions), "events": int(events)}

    @staticmethod
    def _require_privacy_user(user_id: str) -> None:
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("user_id is required")
