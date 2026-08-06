"""Aggregate agent health and memory stats for the extension."""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import Settings, get_settings
from app.db.repositories.memory_repository import MemoryRepository
from app.db.schema import get_connection, migrate
from app.models.agent import AgentLatestMemory, AgentSearchEvent, AgentStatusResponse
from app.models.user import UserPublic


class AgentStatusService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
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

        with get_connection(self._settings) as conn:
            memory_count = _scalar(
                conn,
                "SELECT COUNT(*) AS c FROM memory_records WHERE user_id = ?",
                (user.user_id,),
            )
            today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            today_saves = _scalar(
                conn,
                """
                SELECT COUNT(*) AS c FROM captures
                WHERE user_id = ? AND created_at LIKE ?
                """,
                (user.user_id, f"{today_prefix}%"),
            )
            pending_captures = _scalar(
                conn,
                """
                SELECT COUNT(*) AS c FROM captures
                WHERE user_id = ? AND status IN ('queued', 'processing', 'embedding')
                """,
                (user.user_id,),
            )
            processing_count = pending_captures
            indexed_count = _scalar(
                conn,
                """
                SELECT COUNT(*) AS c FROM captures
                WHERE user_id = ? AND status IN ('completed', 'stored')
                """,
                (user.user_id,),
            )
            pending_jobs = _scalar(
                conn,
                """
                SELECT COUNT(*) AS c FROM background_jobs
                WHERE user_id = ? AND status IN ('queued', 'running', 'paused')
                """,
                (user.user_id,),
            )
            latest_row = conn.execute(
                """
                SELECT memory_id, title, source_type, canonical_url, updated_at
                FROM memory_records
                WHERE user_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (user.user_id,),
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
                    (user.user_id,),
                ).fetchone()
            last_sync = conn.execute(
                """
                SELECT MAX(updated_at) AS ts FROM (
                    SELECT updated_at FROM memory_records WHERE user_id = ?
                    UNION ALL
                    SELECT updated_at FROM captures WHERE user_id = ?
                )
                """,
                (user.user_id, user.user_id),
            ).fetchone()
            search_rows = conn.execute(
                """
                SELECT query, created_at FROM agent_search_events
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT 5
                """,
                (user.user_id,),
            ).fetchall()

        latest = None
        if latest_row:
            latest = AgentLatestMemory(
                memory_id=latest_row["memory_id"],
                title=latest_row["title"] or "",
                source_type=latest_row["source_type"] or "",
                url=latest_row["canonical_url"] or "",
                updated_at=latest_row["updated_at"],
            )

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
            pending_captures=pending_captures,
            pending_jobs=pending_jobs,
            today_saves=today_saves,
            processing_count=processing_count,
            indexed_count=indexed_count,
            memory_count=memory_count or document_count,
            latest_memory=latest,
            recent_searches=[
                AgentSearchEvent(query=r["query"], created_at=r["created_at"]) for r in search_rows
            ],
            last_sync_at=last_sync["ts"] if last_sync else None,
            pwa_url=pwa,
        )

    def record_search(self, *, user_id: str, query: str) -> None:
        q = query.strip()
        if not q:
            return
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT INTO agent_search_events (user_id, query, created_at)
                VALUES (?, ?, ?)
                """,
                (user_id, q[:500], datetime.now(timezone.utc).isoformat()),
            )


def _scalar(conn, sql: str, params: tuple) -> int:
    try:
        row = conn.execute(sql, params).fetchone()
        return int(row["c"] if row and "c" in row.keys() else (row[0] if row else 0))
    except Exception:
        return 0
