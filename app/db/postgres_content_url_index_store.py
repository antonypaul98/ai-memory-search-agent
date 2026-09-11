"""Postgres persistence for cross-connector canonical URL/content deduplication."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

ConnectionFactory = Callable[[], Any]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgresContentUrlIndexStore:
    """Tenant-scoped Postgres adapter for ``content_url_index``."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self._connection_factory() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS content_url_index (
                    user_id TEXT NOT NULL,
                    url_hash TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    content_hash TEXT NOT NULL DEFAULT '',
                    source_type TEXT NOT NULL,
                    connector_id TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    memory_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY (user_id, url_hash)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_content_url_hash
                ON content_url_index(user_id, content_hash)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_content_url_external
                ON content_url_index(user_id, source_type, external_id)
                """
            )

    def find_by_url_hash(self, *, user_id: str, url_hash: str):
        with self._connection_factory() as conn:
            return conn.execute(
                """
                SELECT * FROM content_url_index
                WHERE user_id = %s AND url_hash = %s
                """,
                (user_id, url_hash),
            ).fetchone()

    def find_by_content_hash(self, *, user_id: str, content_hash: str):
        if not content_hash:
            return None
        with self._connection_factory() as conn:
            return conn.execute(
                """
                SELECT * FROM content_url_index
                WHERE user_id = %s AND content_hash = %s AND content_hash != ''
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
        with self._connection_factory() as conn:
            conn.execute(
                """
                INSERT INTO content_url_index (
                    user_id, url_hash, canonical_url, content_hash,
                    source_type, connector_id, external_id, memory_id, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(user_id, url_hash) DO UPDATE SET
                    content_hash = EXCLUDED.content_hash,
                    source_type = EXCLUDED.source_type,
                    connector_id = EXCLUDED.connector_id,
                    external_id = EXCLUDED.external_id,
                    memory_id = EXCLUDED.memory_id
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
        with self._connection_factory() as conn:
            rows = conn.execute(
                "SELECT url_hash FROM content_url_index WHERE user_id = %s",
                (user_id,),
            ).fetchall()
        return {str(row["url_hash"] if isinstance(row, dict) else row[0]) for row in rows}
