"""Aggregate agent health and memory stats for the extension."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config import Settings, get_settings
from app.db.capture_store_factory import get_capture_store
from app.db.intelligence_event_store_factory import get_intelligence_event_store
from app.db.intelligence_store import IntelligenceStore
from app.db.job_store_factory import get_job_store
from app.db.memory_store_factory import get_memory_store
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.repositories.memory_repository import MemoryRepository
from app.db.schema import get_connection, migrate
from app.models.agent import AgentLatestMemory, AgentSearchEvent, AgentStatusResponse
from app.models.user import UserPublic


class AgentStatusService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._postgres = self._settings.memory_store_backend == "postgres"
        self._pg_connect = None
        self._event_store = None
        if self._postgres:
            # Fail closed before any legacy SQLite migration can run. Initializing
            # the selected stores also provisions the exact relational surfaces
            # consumed by the status read without creating an alternate schema.
            self._pg_connect = get_postgres_connection_factory(self._settings)
            get_memory_store(self._settings)
            get_capture_store(self._settings)
            get_job_store(self._settings)
            self._event_store = get_intelligence_event_store(self._settings)
        else:
            migrate(self._settings)

    def get_status(self, user: UserPublic) -> AgentStatusResponse:
        chroma_ok = False
        document_count = 0
        try:
            info = MemoryRepository(self._settings).check_connection()
            chroma_ok = bool(info.get("connected"))
            document_count = int(info.get("document_count") or 0)
        except Exception:
            chroma_ok = False

        if self._postgres:
            values = self._get_postgres_status(user.user_id)
        else:
            values = self._get_sqlite_status(user.user_id)

        backend_status = "ok" if chroma_ok else "degraded"
        pwa = f"http://{self._settings.api_host}:{self._settings.api_port}/"
        if self._settings.api_host in {"0.0.0.0", "::"}:
            pwa = f"http://127.0.0.1:{self._settings.api_port}/"

        return AgentStatusResponse(
            backend_status=backend_status,
            connected=True,
            app_name=self._settings.app_name,
            version="1.1.0",
            chroma_connected=chroma_ok,
            document_count=document_count,
            auth_enabled=self._settings.auth_enabled,
            user_id=user.user_id,
            display_name=user.display_name or "",
            pending_captures=values["pending_captures"],
            pending_jobs=values["pending_jobs"],
            today_saves=values["today_saves"],
            processing_count=values["pending_captures"],
            indexed_count=values["indexed_count"],
            memory_count=values["memory_count"] or document_count,
            latest_memory=values["latest_memory"],
            recent_searches=values["recent_searches"],
            last_sync_at=values["last_sync_at"],
            pwa_url=pwa,
        )

    def record_search(self, *, user_id: str, query: str) -> None:
        q = query.strip()
        if not q:
            return
        bounded_query = q[:500]
        if self._postgres:
            assert self._event_store is not None
            self._event_store.record_event(
                user_id=user_id,
                event_type="search",
                query=bounded_query,
            )
            return

        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT INTO agent_search_events (user_id, query, created_at)
                VALUES (?, ?, ?)
                """,
                (user_id, bounded_query, datetime.now(timezone.utc).isoformat()),
            )
        # Preserve the historical local compatibility row while also mirroring
        # searches into the canonical Memory Intelligence event stream.
        IntelligenceStore(self._settings).record_event(
            user_id=user_id,
            event_type="search",
            query=bounded_query,
        )

    def _get_postgres_status(self, user_id: str) -> dict[str, Any]:
        assert self._pg_connect is not None
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start.replace(day=day_start.day) + _one_day()

        with self._pg_connect() as conn:
            memory_count = _pg_scalar(
                conn,
                "SELECT COUNT(*) AS c FROM memory_records WHERE user_id = %s",
                (user_id,),
            )
            today_saves = _pg_scalar(
                conn,
                "SELECT COUNT(*) AS c FROM captures WHERE user_id = %s AND created_at >= %s AND created_at < %s",
                (user_id, day_start, day_end),
            )
            pending_captures = _pg_scalar(
                conn,
                "SELECT COUNT(*) AS c FROM captures WHERE user_id = %s AND status IN ('queued', 'processing', 'embedding')",
                (user_id,),
            )
            indexed_count = _pg_scalar(
                conn,
                "SELECT COUNT(*) AS c FROM captures WHERE user_id = %s AND status IN ('completed', 'stored')",
                (user_id,),
            )
            pending_jobs = _pg_scalar(
                conn,
                "SELECT COUNT(*) AS c FROM background_jobs WHERE user_id = %s AND status IN ('queued', 'running', 'paused')",
                (user_id,),
            )
            memory_row = conn.execute(
                """
                SELECT memory_id, title, source_type, canonical_url, updated_at
                FROM memory_records
                WHERE user_id = %s
                ORDER BY updated_at DESC, memory_id ASC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
            capture_row = conn.execute(
                """
                SELECT capture_id AS memory_id, title, source_type, url AS canonical_url, updated_at
                FROM captures
                WHERE user_id = %s AND status IN ('completed', 'stored')
                ORDER BY updated_at DESC, capture_id ASC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
            memory_sync = conn.execute(
                "SELECT MAX(updated_at) AS ts FROM memory_records WHERE user_id = %s",
                (user_id,),
            ).fetchone()
            capture_sync = conn.execute(
                "SELECT MAX(updated_at) AS ts FROM captures WHERE user_id = %s",
                (user_id,),
            ).fetchone()

        latest_row = _newer_row(memory_row, capture_row)
        latest = _latest_memory(latest_row)
        last_sync = _newer_timestamp(
            memory_sync["ts"] if memory_sync else None,
            capture_sync["ts"] if capture_sync else None,
        )
        assert self._event_store is not None
        search_rows = self._event_store.recent_events(user_id, event_type="search", limit=5)
        searches = [
            AgentSearchEvent(query=str(row.get("query") or ""), created_at=_as_iso(row.get("created_at")))
            for row in search_rows
            if row.get("query")
        ]
        return {
            "memory_count": memory_count,
            "today_saves": today_saves,
            "pending_captures": pending_captures,
            "indexed_count": indexed_count,
            "pending_jobs": pending_jobs,
            "latest_memory": latest,
            "recent_searches": searches,
            "last_sync_at": _as_iso(last_sync) if last_sync is not None else None,
        }

    def _get_sqlite_status(self, user_id: str) -> dict[str, Any]:
        with get_connection(self._settings) as conn:
            memory_count = _scalar(
                conn,
                "SELECT COUNT(*) AS c FROM memory_records WHERE user_id = ?",
                (user_id,),
            )
            today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            today_saves = _scalar(
                conn,
                "SELECT COUNT(*) AS c FROM captures WHERE user_id = ? AND created_at LIKE ?",
                (user_id, f"{today_prefix}%"),
            )
            pending_captures = _scalar(
                conn,
                "SELECT COUNT(*) AS c FROM captures WHERE user_id = ? AND status IN ('queued', 'processing', 'embedding')",
                (user_id,),
            )
            indexed_count = _scalar(
                conn,
                "SELECT COUNT(*) AS c FROM captures WHERE user_id = ? AND status IN ('completed', 'stored')",
                (user_id,),
            )
            pending_jobs = _scalar(
                conn,
                "SELECT COUNT(*) AS c FROM background_jobs WHERE user_id = ? AND status IN ('queued', 'running', 'paused')",
                (user_id,),
            )
            latest_row = conn.execute(
                """
                SELECT memory_id, title, source_type, canonical_url, updated_at
                FROM memory_records
                WHERE user_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
            if not latest_row:
                latest_row = conn.execute(
                    """
                    SELECT capture_id AS memory_id, title, source_type, url AS canonical_url, updated_at
                    FROM captures
                    WHERE user_id = ? AND status IN ('completed', 'stored')
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (user_id,),
                ).fetchone()
            last_sync = conn.execute(
                """
                SELECT MAX(updated_at) AS ts FROM (
                    SELECT updated_at FROM memory_records WHERE user_id = ?
                    UNION ALL
                    SELECT updated_at FROM captures WHERE user_id = ?
                )
                """,
                (user_id, user_id),
            ).fetchone()
            search_rows = conn.execute(
                """
                SELECT query, created_at FROM agent_search_events
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT 5
                """,
                (user_id,),
            ).fetchall()
        return {
            "memory_count": memory_count,
            "today_saves": today_saves,
            "pending_captures": pending_captures,
            "indexed_count": indexed_count,
            "pending_jobs": pending_jobs,
            "latest_memory": _latest_memory(latest_row),
            "recent_searches": [
                AgentSearchEvent(query=r["query"], created_at=r["created_at"]) for r in search_rows
            ],
            "last_sync_at": last_sync["ts"] if last_sync else None,
        }


def _one_day():
    from datetime import timedelta

    return timedelta(days=1)


def _latest_memory(row: Any | None) -> AgentLatestMemory | None:
    if not row:
        return None
    return AgentLatestMemory(
        memory_id=row["memory_id"],
        title=row["title"] or "",
        source_type=row["source_type"] or "",
        url=row["canonical_url"] or "",
        updated_at=_as_iso(row["updated_at"]),
    )


def _newer_row(first: Any | None, second: Any | None) -> Any | None:
    if not first:
        return second
    if not second:
        return first
    return first if _sort_time(first["updated_at"]) >= _sort_time(second["updated_at"]) else second


def _newer_timestamp(first: Any | None, second: Any | None) -> Any | None:
    if first is None:
        return second
    if second is None:
        return first
    return first if _sort_time(first) >= _sort_time(second) else second


def _sort_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _as_iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _pg_scalar(conn, sql: str, params: tuple) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row["c"] if row else 0)


def _scalar(conn, sql: str, params: tuple) -> int:
    try:
        row = conn.execute(sql, params).fetchone()
        return int(row["c"] if row and "c" in row.keys() else (row[0] if row else 0))
    except Exception:
        return 0
