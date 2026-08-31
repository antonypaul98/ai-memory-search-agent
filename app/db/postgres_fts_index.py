"""Tenant-scoped Postgres lexical index for P-03 search cutover.

This module is deliberately independent from the current SQLite FTS facade so
we can validate the production search primitive before routing live ingestion
or retrieval through it.  Every mutation and query requires an explicit tenant
identifier; there is no global/unscoped fallback.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class PostgresFTSIndex:
    """Postgres full-text index with deterministic, tenant-scoped retrieval."""

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._connection_factory() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_fts_documents (
                    user_id TEXT NOT NULL,
                    video_id TEXT NOT NULL,
                    level TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    body TEXT NOT NULL DEFAULT '',
                    search_document TSVECTOR GENERATED ALWAYS AS (
                        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
                        setweight(to_tsvector('english', coalesce(body, '')), 'B')
                    ) STORED,
                    PRIMARY KEY (user_id, doc_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_fts_documents_search
                ON memory_fts_documents USING GIN(search_document)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_fts_documents_tenant_video
                ON memory_fts_documents(user_id, video_id, doc_id)
                """
            )

    def upsert(
        self,
        *,
        user_id: str,
        video_id: str,
        level: str,
        doc_id: str,
        title: str,
        body: str,
    ) -> None:
        if not user_id.strip():
            raise ValueError("user_id is required for lexical indexing")
        with self._connection_factory() as conn:
            conn.execute(
                """
                INSERT INTO memory_fts_documents (
                    user_id, video_id, level, doc_id, title, body
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, doc_id) DO UPDATE SET
                    video_id = EXCLUDED.video_id,
                    level = EXCLUDED.level,
                    title = EXCLUDED.title,
                    body = EXCLUDED.body
                """,
                (user_id, video_id, level, doc_id, title, body),
            )

    def search(
        self,
        query: str,
        *,
        user_id: str,
        limit: int = 20,
        video_ids: list[str] | None = None,
    ) -> list[dict]:
        """Return deterministic lexical hits for exactly one tenant."""
        if not query.strip():
            return []
        if not user_id.strip():
            raise ValueError("user_id is required for lexical search")
        bounded_limit = max(1, min(int(limit), 100))

        params: list[Any] = [query, user_id]
        video_clause = ""
        if video_ids:
            video_clause = " AND video_id = ANY(%s)"
            params.append(list(video_ids))
        params.append(bounded_limit)

        with self._connection_factory() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    doc_id,
                    video_id,
                    level,
                    title,
                    ts_headline(
                        'english', body, lexical_query,
                        'StartSel=[,StopSel=],MaxWords=20,MinWords=5'
                    ) AS snippet,
                    ts_rank_cd(search_document, lexical_query) AS score
                FROM memory_fts_documents,
                     websearch_to_tsquery('english', %s) AS lexical_query
                WHERE user_id = %s
                  AND search_document @@ lexical_query
                  {video_clause}
                ORDER BY score DESC, doc_id ASC
                LIMIT %s
                """,
                tuple(params),
            ).fetchall()

        results: list[dict] = []
        for rank, row in enumerate(rows, start=1):
            results.append(
                {
                    "doc_id": row["doc_id"],
                    "video_id": row["video_id"],
                    "level": row["level"],
                    "title": row["title"],
                    "matched_text": row.get("snippet") or "",
                    # Keep the historical lexical score shape stable for RRF/MMR;
                    # Postgres' score determines ordering, while this normalized
                    # value avoids backend-specific score magnitudes leaking out.
                    "relevance_score": max(0.1, 1.0 / rank),
                    "rank": rank,
                }
            )
        return results

    def delete_video(self, video_id: str, *, user_id: str) -> None:
        if not user_id.strip():
            raise ValueError("user_id is required for lexical deletion")
        with self._connection_factory() as conn:
            conn.execute(
                "DELETE FROM memory_fts_documents WHERE user_id = %s AND video_id = %s",
                (user_id, video_id),
            )
