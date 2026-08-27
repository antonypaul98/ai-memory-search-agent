"""Phase 2 semantic cache operations and tenant isolation tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.db.schema import get_connection
from app.services.semantic_cache import SemanticCache


def _enabled(settings: Settings) -> Settings:
    """Enable the feature explicitly; the shared fixture disables cache by default."""
    return settings.model_copy(update={"semantic_cache_enabled": True})


def _put(cache: SemanticCache, user_id: str, question: str, query_type: str = "factual") -> None:
    cache.put(
        question=question,
        query_embedding=[1.0, 0.0],
        answer={"answer": question},
        query_type=query_type,
        user_id=user_id,
    )


class TestSemanticCacheOperations:
    def test_stats_are_tenant_scoped(self, test_settings: Settings) -> None:
        settings = _enabled(test_settings)
        cache = SemanticCache(settings)
        _put(cache, "user-a", "alpha")
        _put(cache, "user-a", "beta", "comparison")
        _put(cache, "user-b", "private")

        stats = cache.stats(user_id="user-a")
        assert stats["total"] == 2
        assert stats["active"] == 2
        assert stats["expired"] == 0
        assert stats["active_by_query_type"] == {"comparison": 1, "factual": 1}

    def test_stats_count_expired_without_returning_content(self, test_settings: Settings) -> None:
        settings = _enabled(test_settings)
        cache = SemanticCache(settings)
        _put(cache, "user-a", "old")
        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        with get_connection(settings) as conn:
            conn.execute(
                "UPDATE semantic_cache SET expires_at = ? WHERE user_id = ?",
                (past, "user-a"),
            )

        stats = cache.stats(user_id="user-a")
        assert stats["total"] == 1
        assert stats["active"] == 0
        assert stats["expired"] == 1
        assert "old" not in str(stats)

    def test_invalidate_only_current_tenant(self, test_settings: Settings) -> None:
        cache = SemanticCache(_enabled(test_settings))
        _put(cache, "user-a", "alpha")
        _put(cache, "user-b", "beta")

        assert cache.invalidate(user_id="user-a") == 1
        assert cache.stats(user_id="user-a")["total"] == 0
        assert cache.stats(user_id="user-b")["total"] == 1

    def test_invalidate_can_limit_query_type(self, test_settings: Settings) -> None:
        cache = SemanticCache(_enabled(test_settings))
        _put(cache, "user-a", "alpha", "factual")
        _put(cache, "user-a", "beta", "comparison")

        assert cache.invalidate(user_id="user-a", query_type="factual") == 1
        stats = cache.stats(user_id="user-a")
        assert stats["total"] == 1
        assert stats["active_by_query_type"] == {"comparison": 1}


class TestSemanticCacheAPI:
    def test_stats_endpoint(self, client: TestClient, test_settings: Settings) -> None:
        cache = SemanticCache(_enabled(test_settings))
        _put(cache, "local-default", "cached question")

        resp = client.get("/api/v1/cache/semantic/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["active"] == 1
        assert "answer" not in body

    def test_invalidation_endpoint(self, client: TestClient, test_settings: Settings) -> None:
        cache = SemanticCache(_enabled(test_settings))
        _put(cache, "local-default", "one", "factual")
        _put(cache, "local-default", "two", "comparison")

        resp = client.delete("/api/v1/cache/semantic?query_type=factual")
        assert resp.status_code == 200
        assert resp.json()["removed"] == 1
        assert cache.stats(user_id="local-default")["total"] == 1

    def test_invalidation_rejects_empty_query_type(self, client: TestClient) -> None:
        resp = client.delete("/api/v1/cache/semantic?query_type=")
        assert resp.status_code == 422
