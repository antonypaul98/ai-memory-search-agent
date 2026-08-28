"""Durable domain event bus with audit log and opt-in webhook subscriptions.

Phase 4 keeps the abstraction deliberately small: publish typed events, persist an
immutable audit row, expose tenant-scoped metrics, notify local subscribers, and
deliver privacy-safe events to explicitly confirmed webhook subscriptions. The
interface can later be backed by Redis/NATS without changing producers.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.db.schema import get_connection
from app.models.event import MemoryEvent, WebhookSubscription
from app.services.ssrf_fetch import validate_public_http_url

logger = logging.getLogger(__name__)
EventHandler = Callable[[MemoryEvent], None]

_SENSITIVE_KEYS = {
    "access_token",
    "refresh_token",
    "authorization",
    "password",
    "secret",
    "api_key",
    "apikey",
    "client_secret",
    "connector_token_key",
}


def _redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if str(key).strip().lower() in _SENSITIVE_KEYS
                else _redact_payload(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_payload(item) for item in value]
    return value


class EventBus:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._lock = threading.RLock()
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create the Phase-4 audit and webhook tables idempotently."""
        with get_connection(self._settings) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    aggregate_type TEXT NOT NULL DEFAULT '',
                    aggregate_id TEXT NOT NULL DEFAULT '',
                    actor TEXT NOT NULL DEFAULT 'system',
                    request_id TEXT,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memory_events_user_id
                    ON memory_events(user_id, id);
                CREATE INDEX IF NOT EXISTS idx_memory_events_user_type_id
                    ON memory_events(user_id, event_type, id);
                CREATE INDEX IF NOT EXISTS idx_memory_events_user_request_id
                    ON memory_events(user_id, request_id, id);

                CREATE TABLE IF NOT EXISTS webhook_subscriptions (
                    subscription_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL DEFAULT '*',
                    url TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_webhook_subscriptions_user
                    ON webhook_subscriptions(user_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_webhook_subscriptions_delivery
                    ON webhook_subscriptions(user_id, active, event_type);
                """
            )

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        key = (event_type or "*").strip() or "*"
        with self._lock:
            handlers = self._subscribers.setdefault(key, [])
            if handler not in handlers:
                handlers.append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        key = (event_type or "*").strip() or "*"
        with self._lock:
            handlers = self._subscribers.get(key, [])
            if handler in handlers:
                handlers.remove(handler)

    def create_webhook_subscription(
        self, *, user_id: str, url: str, event_type: str = "*"
    ) -> WebhookSubscription:
        user_id = (user_id or "").strip()
        event_type = (event_type or "*").strip() or "*"
        if not user_id:
            raise ValueError("user_id is required")
        if len(event_type) > 120:
            raise ValueError("event_type is too long")
        # Creation validates scheme/host/private literal without requiring a DNS
        # lookup. Delivery revalidates DNS immediately before the outbound POST.
        safe_url = validate_public_http_url(url, resolve_dns=False)
        subscription = WebhookSubscription(
            subscription_id=str(uuid.uuid4()),
            event_type=event_type,
            url=safe_url,
            active=True,
            created_at=datetime.now(timezone.utc),
        )
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT INTO webhook_subscriptions (
                    subscription_id, user_id, event_type, url, active, created_at
                ) VALUES (?, ?, ?, ?, 1, ?)
                """,
                (
                    subscription.subscription_id,
                    user_id,
                    subscription.event_type,
                    str(subscription.url),
                    subscription.created_at.isoformat(),
                ),
            )
        return subscription

    def list_webhook_subscriptions(self, *, user_id: str) -> list[WebhookSubscription]:
        user_id = (user_id or "").strip()
        if not user_id:
            raise ValueError("user_id is required")
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                """
                SELECT subscription_id, event_type, url, active, created_at
                FROM webhook_subscriptions
                WHERE user_id = ?
                ORDER BY created_at ASC, subscription_id ASC
                """,
                (user_id,),
            ).fetchall()
        return [
            WebhookSubscription(
                subscription_id=row["subscription_id"],
                event_type=row["event_type"],
                url=row["url"],
                active=bool(row["active"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def delete_webhook_subscription(self, *, user_id: str, subscription_id: str) -> bool:
        user_id = (user_id or "").strip()
        subscription_id = (subscription_id or "").strip()
        if not user_id:
            raise ValueError("user_id is required")
        if not subscription_id:
            raise ValueError("subscription_id is required")
        with get_connection(self._settings) as conn:
            cursor = conn.execute(
                "DELETE FROM webhook_subscriptions WHERE user_id = ? AND subscription_id = ?",
                (user_id, subscription_id),
            )
        return cursor.rowcount > 0

    def emit(
        self,
        *,
        user_id: str,
        event_type: str,
        aggregate_type: str = "",
        aggregate_id: str = "",
        actor: str = "system",
        request_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> MemoryEvent:
        user_id = (user_id or "").strip()
        event_type = (event_type or "").strip()
        if not user_id:
            raise ValueError("user_id is required")
        if not event_type:
            raise ValueError("event_type is required")
        if len(event_type) > 120:
            raise ValueError("event_type is too long")

        event = MemoryEvent(
            event_id=str(uuid.uuid4()),
            user_id=user_id,
            event_type=event_type,
            aggregate_type=(aggregate_type or "").strip()[:80],
            aggregate_id=(aggregate_id or "").strip()[:240],
            actor=(actor or "system").strip()[:120] or "system",
            request_id=(request_id or "").strip()[:120] or None,
            payload=_redact_payload(dict(payload or {})),
            created_at=datetime.now(timezone.utc),
        )

        try:
            payload_json = json.dumps(event.payload, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValueError("event payload must be JSON serializable") from exc

        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT INTO memory_events (
                    event_id, user_id, event_type, aggregate_type, aggregate_id,
                    actor, request_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.user_id,
                    event.event_type,
                    event.aggregate_type,
                    event.aggregate_id,
                    event.actor,
                    event.request_id,
                    payload_json,
                    event.created_at.isoformat(),
                ),
            )

        with self._lock:
            handlers = list(self._subscribers.get(event.event_type, ())) + list(
                self._subscribers.get("*", ())
            )
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                logger.exception("event subscriber failed for %s", event.event_type)

        self._deliver_webhooks(event)
        return event

    def _deliver_webhooks(self, event: MemoryEvent) -> None:
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                """
                SELECT url
                FROM webhook_subscriptions
                WHERE user_id = ? AND active = 1 AND event_type IN ('*', ?)
                ORDER BY created_at ASC, subscription_id ASC
                """,
                (event.user_id, event.event_type),
            ).fetchall()
        if not rows:
            return

        body = {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "aggregate_type": event.aggregate_type,
            "aggregate_id": event.aggregate_id,
            "actor": event.actor,
            "request_id": event.request_id,
            "payload": event.payload,
            "created_at": event.created_at.isoformat(),
        }
        for row in rows:
            try:
                safe_url = validate_public_http_url(row["url"], resolve_dns=True)
                with httpx.Client(timeout=5.0, follow_redirects=False) as client:
                    response = client.post(
                        safe_url,
                        json=body,
                        headers={"User-Agent": "ai-memory-search-agent-webhook/1"},
                    )
                    response.raise_for_status()
            except Exception:
                # Webhooks are observability side effects. Never turn an already
                # committed memory operation into a failure because delivery failed.
                logger.exception("webhook delivery failed for event %s", event.event_id)

    def list_events(
        self,
        *,
        user_id: str,
        event_type: str | None = None,
        after_id: int | None = None,
        request_id: str | None = None,
        limit: int = 100,
    ) -> tuple[list[MemoryEvent], int | None]:
        if not user_id:
            raise ValueError("user_id is required")
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if request_id:
            clauses.append("request_id = ?")
            params.append(request_id)
        if after_id is not None:
            if after_id < 0:
                raise ValueError("after_id must be non-negative")
            clauses.append("id > ?")
            params.append(after_id)
        params.append(limit)

        with get_connection(self._settings) as conn:
            rows = conn.execute(
                f"""
                SELECT id, event_id, user_id, event_type, aggregate_type,
                       aggregate_id, actor, request_id, payload_json, created_at
                FROM memory_events
                WHERE {' AND '.join(clauses)}
                ORDER BY id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()

        events = [
            MemoryEvent(
                event_id=row["event_id"],
                user_id=row["user_id"],
                event_type=row["event_type"],
                aggregate_type=row["aggregate_type"],
                aggregate_id=row["aggregate_id"],
                actor=row["actor"],
                request_id=row["request_id"],
                payload=json.loads(row["payload_json"] or "{}"),
                created_at=row["created_at"],
            )
            for row in rows
        ]
        next_after_id = int(rows[-1]["id"]) if rows else after_id
        return events, next_after_id

    def metrics(self, *, user_id: str) -> dict[str, int]:
        """Return durable per-event counters scoped to one tenant."""
        user_id = (user_id or "").strip()
        if not user_id:
            raise ValueError("user_id is required")
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                """
                SELECT event_type, COUNT(*) AS event_count
                FROM memory_events
                WHERE user_id = ?
                GROUP BY event_type
                ORDER BY event_type ASC
                """,
                (user_id,),
            ).fetchall()
        return {row["event_type"]: int(row["event_count"]) for row in rows}
