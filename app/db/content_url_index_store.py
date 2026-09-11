"""SQLite persistence for cross-connector canonical URL/content deduplication."""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import Settings, get_settings
from app.db.schema import get_connection, migrate


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ContentUrlIndexStore:
    """Tenant-scoped SQLite adapter for ``content_url_index``."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        migrate(self._settings)

    def find_by_url_hash(self, *, user_id: str, url_hash: str):
        with get_connection(self._settings) as conn:
            return conn.execute(
                """
                SELECT * FROM content_url_index
                WHERE user_id = ? AND url_hash = ?
                """,
                (user_id, url_hash),
            ).fetchone()

    def find_by_content_hash(self, *, user_id: str, content_hash: str):
        if not content_hash:
            return None
        with get_connection(self._settings) as conn:
            return conn.execute(
                """
                SELECT * FROM content_url_index
                WHERE user_id = ? AND content_hash = ? AND content_hash != ''
                ORDER BY created_at ASC, url_hash ASC
                LIMIT 1
                """,
                (user_id, content_hash),
            ).fetchone()

    def register(
        self,
        *,
        user_id: str,
        url_hash: str,
        canonical_url: str,
        content_hash: str,
        source_type: str,
        connector_id: str,
        external_id: str,
        memory_id: str | None = None,
        created_at: str | None = None,
    ) -> None:
        now = created_at or _utc_now()
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT INTO content_url_index (
                    user_id, url_hash, canonical_url, content_hash,
                    source_type, connector_id, external_id, memory_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, url_hash) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    source_type = excluded.source_type,
                    connector_id = excluded.connector_id,
                    external_id = excluded.external_id,
                    memory_id = excluded.memory_id
                """,
                (
                    user_id,
                    url_hash,
                    canonical_url,
                    content_hash or "",
                    source_type,
                    connector_id,
                    external_id,
                    memory_id,
                    now,
                ),
            )

    def known_url_hashes(self, *, user_id: str) -> set[str]:
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                "SELECT url_hash FROM content_url_index WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        return {str(row["url_hash"]) for row in rows}

    def delete_reference(self, *, user_id: str, source_type: str, external_id: str) -> int:
        """Delete exactly one tenant's references for a source item."""
        with get_connection(self._settings) as conn:
            cursor = conn.execute(
                """
                DELETE FROM content_url_index
                WHERE user_id = ? AND source_type = ? AND external_id = ?
                """,
                (user_id, source_type, external_id),
            )
            return max(0, int(cursor.rowcount or 0))
