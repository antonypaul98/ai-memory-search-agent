"""Semantic query response cache with tenant isolation."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import numpy as np

from app.config import Settings, get_settings
from app.db.schema import get_connection, migrate, get_index_version, get_preference_version
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


class SemanticCache:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        migrate(self._settings)

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
        index_v = get_index_version(self._settings)
        pref_v = get_preference_version(self._settings)
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
            best = None
            best_sim = 0.0
            for row in rows:
                if not row["question_embedding"]:
                    continue
                emb = json.loads(row["question_embedding"])
                sim = _cosine(query_embedding, emb)
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
        if not self._settings.semantic_cache_enabled:
            return
        if query_type in {"ambiguous"}:
            return
        owner = user_id or LOCAL_DEFAULT_USER_ID
        normalized = normalize_question(question)
        cache_key = _cache_key(owner, normalized)
        index_v = get_index_version(self._settings)
        pref_v = get_preference_version(self._settings)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=self._settings.semantic_cache_ttl_sec)
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
