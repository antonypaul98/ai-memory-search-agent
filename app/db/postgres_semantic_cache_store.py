"""Tenant-scoped Postgres persistence for semantic/query cache state.

Credentials are resolved by the shared Postgres runtime and are never persisted here.
Cache rows and the version metadata that invalidate them live in the same backend so a
Postgres production profile cannot silently retain SQLite cache writes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

ConnectionFactory = Callable[[], Any]


class PostgresSemanticCacheStore:
    """Persist semantic cache entries and cache-version metadata in Postgres."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self._connection_factory() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO cache_meta (key, value)
                VALUES ('memory_index_version', '1'), ('preference_version', '1')
                ON CONFLICT (key) DO NOTHING
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS semantic_cache (
                    user_id TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    question_normalized TEXT NOT NULL,
                    question_embedding BYTEA,
                    answer_json TEXT NOT NULL,
                    query_type TEXT NOT NULL,
                    memory_index_version TEXT NOT NULL,
                    preference_version TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY (user_id, cache_key)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_semantic_cache_tenant_active
                ON semantic_cache(user_id, expires_at, query_type)
                """
            )

    def versions(self) -> tuple[str, str]:
        with self._connection_factory() as conn:
            rows = conn.execute(
                "SELECT key, value FROM cache_meta WHERE key IN ('memory_index_version', 'preference_version')"
            ).fetchall()
        values = {str(row["key"]): str(row["value"]) for row in rows}
        return values.get("memory_index_version", "1"), values.get("preference_version", "1")

    def bump_index_version(self) -> str:
        """Atomically advance index version and invalidate stale cached answers."""
        with self._connection_factory() as conn:
            row = conn.execute(
                """
                INSERT INTO cache_meta (key, value) VALUES ('memory_index_version', '2')
                ON CONFLICT (key) DO UPDATE
                SET value = (cache_meta.value::BIGINT + 1)::TEXT
                RETURNING value
                """
            ).fetchone()
            conn.execute("DELETE FROM semantic_cache")
            return str(row["value"])

    def upsert(
        self,
        *,
        user_id: str,
        cache_key: str,
        question_normalized: str,
        question_embedding: bytes | None,
        answer_json: str,
        query_type: str,
        memory_index_version: str,
        preference_version: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        self._require_user(user_id)
        with self._connection_factory() as conn:
            conn.execute(
                """
                INSERT INTO semantic_cache (
                    user_id, cache_key, question_normalized, question_embedding, answer_json,
                    query_type, memory_index_version, preference_version, created_at, expires_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, cache_key) DO UPDATE SET
                    question_normalized = EXCLUDED.question_normalized,
                    question_embedding = EXCLUDED.question_embedding,
                    answer_json = EXCLUDED.answer_json,
                    query_type = EXCLUDED.query_type,
                    memory_index_version = EXCLUDED.memory_index_version,
                    preference_version = EXCLUDED.preference_version,
                    created_at = EXCLUDED.created_at,
                    expires_at = EXCLUDED.expires_at
                """,
                (
                    user_id, cache_key, question_normalized, question_embedding, answer_json,
                    query_type, memory_index_version, preference_version, created_at, expires_at,
                ),
            )

    def get_exact(
        self,
        *,
        user_id: str,
        cache_key: str,
        query_type: str,
        memory_index_version: str,
        preference_version: str,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        self._require_user(user_id)
        current = now or datetime.now(timezone.utc)
        with self._connection_factory() as conn:
            row = conn.execute(
                """
                SELECT cache_key, question_normalized, question_embedding, answer_json, query_type,
                       memory_index_version, preference_version, created_at, expires_at
                FROM semantic_cache
                WHERE user_id = %s AND cache_key = %s AND query_type = %s
                  AND memory_index_version = %s AND preference_version = %s
                  AND expires_at > %s
                """,
                (user_id, cache_key, query_type, memory_index_version, preference_version, current),
            ).fetchone()
        return dict(row) if row else None

    def active_candidates(
        self,
        *,
        user_id: str,
        query_type: str,
        memory_index_version: str,
        preference_version: str,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        self._require_user(user_id)
        current = now or datetime.now(timezone.utc)
        with self._connection_factory() as conn:
            rows = conn.execute(
                """
                SELECT cache_key, question_normalized, question_embedding, answer_json, query_type,
                       memory_index_version, preference_version, created_at, expires_at
                FROM semantic_cache
                WHERE user_id = %s AND query_type = %s
                  AND memory_index_version = %s AND preference_version = %s
                  AND expires_at > %s
                ORDER BY cache_key ASC
                """,
                (user_id, query_type, memory_index_version, preference_version, current),
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self, *, user_id: str, now: datetime | None = None) -> dict[str, Any]:
        """Return tenant-only aggregate counts without cached question/answer content."""
        self._require_user(user_id)
        current = now or datetime.now(timezone.utc)
        with self._connection_factory() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE expires_at > %s) AS active,
                       COUNT(*) FILTER (WHERE expires_at <= %s) AS expired
                FROM semantic_cache
                WHERE user_id = %s
                """,
                (current, current, user_id),
            ).fetchone()
            by_type_rows = conn.execute(
                """
                SELECT query_type, COUNT(*) AS count
                FROM semantic_cache
                WHERE user_id = %s AND expires_at > %s
                GROUP BY query_type
                ORDER BY query_type
                """,
                (user_id, current),
            ).fetchall()
        return {
            "total": int(row["total"] or 0),
            "active": int(row["active"] or 0),
            "expired": int(row["expired"] or 0),
            "active_by_query_type": {str(item["query_type"]): int(item["count"]) for item in by_type_rows},
        }

    def invalidate(self, *, user_id: str, query_type: str | None = None) -> int:
        self._require_user(user_id)
        with self._connection_factory() as conn:
            if query_type is None:
                result = conn.execute("DELETE FROM semantic_cache WHERE user_id = %s", (user_id,))
            else:
                result = conn.execute(
                    "DELETE FROM semantic_cache WHERE user_id = %s AND query_type = %s",
                    (user_id, query_type),
                )
            return max(int(getattr(result, "rowcount", 0)), 0)

    @staticmethod
    def _require_user(user_id: str) -> None:
        if not user_id or not user_id.strip():
            raise ValueError("semantic cache operations require explicit tenant identity")
