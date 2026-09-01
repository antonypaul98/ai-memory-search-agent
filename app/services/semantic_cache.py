"""Semantic query response cache with tenant isolation and operator controls."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from app.config import Settings, get_settings
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.postgres_semantic_cache_store import PostgresSemanticCacheStore
from app.db.schema import (
    bump_index_version,
    get_connection,
    get_index_version,
    get_preference_version,
    invalidate_semantic_cache,
    migrate,
)
from app.models.user import LOCAL_DEFAULT_USER_ID


def normalize_question(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip().lower())


def _cosine(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=float)
    vb = np.array(b, dtype=float)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def _cache_key(user_id: str, normalized_question: str) -> str:
    """Namespace the primary key so identical questions cannot overwrite another tenant."""
    return f"{user_id}:{normalized_question}"


def _decode_embedding(value: Any) -> list[float]:
    if value is None:
        return []
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return list(json.loads(value))
    return list(value)


class SemanticCache:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._postgres: PostgresSemanticCacheStore | None = None
        if self._settings.semantic_cache_store_backend == "postgres":
            self._postgres = PostgresSemanticCacheStore(
                get_postgres_connection_factory(self._settings)
            )
        else:
            migrate(self._settings)

    def _versions(self) -> tuple[str, str]:
        if self._postgres is not None:
            return self._postgres.versions()
        return get_index_version(self._settings), get_preference_version(self._settings)

    def get(
        self,
        *,
        question: str,
        query_embedding: list[float],
        query_type: str,
        user_id: str | None = None,
    ) -> dict | None:
        if not self._settings.semantic_cache_enabled:
            return None
        owner = user_id or LOCAL_DEFAULT_USER_ID
        normalized = normalize_question(question)
        cache_key = _cache_key(owner, normalized)
        index_v, pref_v = self._versions()

        if self._postgres is not None:
            now = datetime.now(timezone.utc)
            exact = self._postgres.get_exact(
                user_id=owner,
                cache_key=cache_key,
                query_type=query_type,
                memory_index_version=index_v,
                preference_version=pref_v,
                now=now,
            )
            if exact:
                return {"answer": json.loads(exact["answer_json"]), "cache_type": "exact"}
            if query_type in {"ambiguous", "reflection"}:
                return None
            rows = self._postgres.active_candidates(
                user_id=owner,
                query_type=query_type,
                memory_index_version=index_v,
                preference_version=pref_v,
                now=now,
            )
            return self._best_semantic(rows, query_embedding)

        now = datetime.now(timezone.utc).isoformat()
        with get_connection(self._settings) as conn:
            exact = conn.execute(
                """
                SELECT answer_json FROM semantic_cache
                WHERE cache_key = ? AND user_id = ?
                  AND memory_index_version = ? AND preference_version = ?
                  AND expires_at > ? AND query_type = ?
                """,
                (cache_key, owner, index_v, pref_v, now, query_type),
            ).fetchone()
            if exact:
                return {"answer": json.loads(exact["answer_json"]), "cache_type": "exact"}
            if query_type in {"ambiguous", "reflection"}:
                return None
            rows = conn.execute(
                """
                SELECT question_embedding, answer_json FROM semantic_cache
                WHERE user_id = ? AND memory_index_version = ? AND preference_version = ?
                  AND expires_at > ? AND query_type = ?
                """,
                (owner, index_v, pref_v, now, query_type),
            ).fetchall()
            return self._best_semantic(rows, query_embedding)

    def _best_semantic(self, rows: list[Any], query_embedding: list[float]) -> dict | None:
        best = None
        best_sim = 0.0
        for row in rows:
            embedding = row["question_embedding"]
            if not embedding:
                continue
            sim = _cosine(query_embedding, _decode_embedding(embedding))
            if sim > best_sim:
                best_sim = sim
                best = row
        if best and best_sim >= self._settings.semantic_cache_similarity_threshold:
            return {
                "answer": json.loads(best["answer_json"]),
                "cache_type": "semantic",
                "similarity": best_sim,
            }
        return None

    def put(
        self,
        *,
        question: str,
        query_embedding: list[float],
        answer: dict,
        query_type: str,
        user_id: str | None = None,
    ) -> None:
        if not self._settings.semantic_cache_enabled or query_type == "ambiguous":
            return
        owner = user_id or LOCAL_DEFAULT_USER_ID
        normalized = normalize_question(question)
        cache_key = _cache_key(owner, normalized)
        index_v, pref_v = self._versions()
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=self._settings.semantic_cache_ttl_sec)

        if self._postgres is not None:
            self._postgres.upsert(
                user_id=owner,
                cache_key=cache_key,
                question_normalized=normalized,
                question_embedding=json.dumps(query_embedding).encode("utf-8"),
                answer_json=json.dumps(answer),
                query_type=query_type,
                memory_index_version=index_v,
                preference_version=pref_v,
                created_at=now,
                expires_at=expires,
            )
            return

        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO semantic_cache
                (cache_key, question_normalized, question_embedding, answer_json, query_type,
                 memory_index_version, preference_version, created_at, expires_at, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cache_key,
                    normalized,
                    json.dumps(query_embedding),
                    json.dumps(answer),
                    query_type,
                    index_v,
                    pref_v,
                    now.isoformat(),
                    expires.isoformat(),
                    owner,
                ),
            )

    def stats(self, *, user_id: str | None = None) -> dict:
        """Return cache counts for one tenant without exposing cached content."""
        owner = user_id or LOCAL_DEFAULT_USER_ID
        if self._postgres is not None:
            counts = self._postgres.stats(user_id=owner)
        else:
            now = datetime.now(timezone.utc).isoformat()
            with get_connection(self._settings) as conn:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS total,
                        SUM(CASE WHEN expires_at > ? THEN 1 ELSE 0 END) AS active,
                        SUM(CASE WHEN expires_at <= ? THEN 1 ELSE 0 END) AS expired
                    FROM semantic_cache WHERE user_id = ?
                    """,
                    (now, now, owner),
                ).fetchone()
                by_type_rows = conn.execute(
                    """
                    SELECT query_type, COUNT(*) AS count FROM semantic_cache
                    WHERE user_id = ? AND expires_at > ?
                    GROUP BY query_type ORDER BY query_type
                    """,
                    (owner, now),
                ).fetchall()
            counts = {
                "total": int(row["total"] or 0),
                "active": int(row["active"] or 0),
                "expired": int(row["expired"] or 0),
                "active_by_query_type": {r["query_type"]: int(r["count"]) for r in by_type_rows},
            }
        return {
            "enabled": self._settings.semantic_cache_enabled,
            "ttl_sec": self._settings.semantic_cache_ttl_sec,
            "similarity_threshold": self._settings.semantic_cache_similarity_threshold,
            **counts,
        }

    def invalidate(
        self,
        *,
        user_id: str | None = None,
        query_type: str | None = None,
    ) -> int:
        """Delete cache entries for exactly one tenant; optionally limit by query type."""
        owner = user_id or LOCAL_DEFAULT_USER_ID
        if self._postgres is not None:
            return self._postgres.invalidate(user_id=owner, query_type=query_type)
        with get_connection(self._settings) as conn:
            if query_type is None:
                cur = conn.execute("DELETE FROM semantic_cache WHERE user_id = ?", (owner,))
            else:
                cur = conn.execute(
                    "DELETE FROM semantic_cache WHERE user_id = ? AND query_type = ?",
                    (owner, query_type),
                )
            return max(int(cur.rowcount or 0), 0)

    def bump_index_version_and_invalidate(self) -> str:
        """Advance the selected cache version and invalidate stale answers in that backend only."""
        if self._postgres is not None:
            return self._postgres.bump_index_version()
        version = bump_index_version(self._settings)
        invalidate_semantic_cache(self._settings)
        return version
