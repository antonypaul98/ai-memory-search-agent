"""Durable in-process domain event bus with a SQLite audit log.

Phase 4 starts with a deliberately small abstraction: publish typed events, persist
an immutable audit row, and notify local subscribers. The interface can later be
backed by Redis/NATS without changing producers.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from app.config import Settings, get_settings
from app.db.schema import get_connection
from app.models.event import MemoryEvent

logger = logging.getLogger(__name__)
EventHandler = Callable[[MemoryEvent], None]


class EventBus:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._lock = threading.RLock()
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create the Phase-4 audit table idempotently.

        The table is self-initializing so the event foundation can be introduced
        without making older databases unreadable. A later production-scale
        migration can externalize this store behind the same interface.
        """
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
            payload=dict(payload or {}),
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
        return event

    def list_events(
        self,
        *,
        user_id: str,
        event_type: str | None = None,
        after_id: int | None = None,
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
