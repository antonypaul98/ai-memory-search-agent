"""Regression tests for tenant-scoped semantic retrieval cache."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.config import Settings
from app.db.schema import get_connection, migrate
from app.services.ahme_engine import AdaptiveHierarchicalMemoryEngine
from app.services.semantic_cache import SemanticCache


def _settings(tmp_path) -> Settings:
    return Settings(
        sqlite_path=str(tmp_path / "cache.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        semantic_cache_enabled=True,
        semantic_cache_similarity_threshold=0.5,
    )


def test_exact_cache_is_isolated_per_user(tmp_path) -> None:
    settings = _settings(tmp_path)
    migrate(settings)
    cache = SemanticCache(settings)
    embedding = [1.0, 0.0, 0.0]

    cache.put(
        question="What GPU do I need?",
        query_embedding=embedding,
        answer={"chunks": [{"matched_text": "user-a answer"}]},
        query_type="exact_lookup",
        user_id="user-a",
    )

    own = cache.get(
        question="What GPU do I need?",
        query_embedding=embedding,
        query_type="exact_lookup",
        user_id="user-a",
    )
    other = cache.get(
        question="What GPU do I need?",
        query_embedding=embedding,
        query_type="exact_lookup",
        user_id="user-b",
    )

    assert own is not None
    assert own["answer"]["chunks"][0]["matched_text"] == "user-a answer"
    assert other is None


def test_identical_questions_do_not_overwrite_other_tenants(tmp_path) -> None:
    settings = _settings(tmp_path)
    migrate(settings)
    cache = SemanticCache(settings)
    embedding = [1.0, 0.0, 0.0]

    for user_id, text in (("user-a", "answer-a"), ("user-b", "answer-b")):
        cache.put(
            question="same question",
            query_embedding=embedding,
            answer={"chunks": [{"matched_text": text}]},
            query_type="exact_lookup",
            user_id=user_id,
        )

    a = cache.get(
        question="same question",
        query_embedding=embedding,
        query_type="exact_lookup",
        user_id="user-a",
    )
    b = cache.get(
        question="same question",
        query_embedding=embedding,
        query_type="exact_lookup",
        user_id="user-b",
    )

    assert a["answer"]["chunks"][0]["matched_text"] == "answer-a"
    assert b["answer"]["chunks"][0]["matched_text"] == "answer-b"
    with get_connection(settings) as conn:
        rows = conn.execute(
            "SELECT cache_key, user_id FROM semantic_cache ORDER BY user_id"
        ).fetchall()
    assert len(rows) == 2
    assert rows[0]["cache_key"].startswith("user-a:")
    assert rows[1]["cache_key"].startswith("user-b:")


def test_semantic_reuse_does_not_cross_query_types(tmp_path) -> None:
    settings = _settings(tmp_path)
    migrate(settings)
    cache = SemanticCache(settings)
    embedding = [1.0, 0.0, 0.0]
    cache.put(
        question="gpu recommendation",
        query_embedding=embedding,
        answer={"chunks": [{"matched_text": "cached exact lookup"}]},
        query_type="exact_lookup",
        user_id="user-a",
    )

    miss = cache.get(
        question="how should I install my gpu?",
        query_embedding=embedding,
        query_type="procedural",
        user_id="user-a",
    )
    assert miss is None


def test_ahme_passes_user_id_to_cache(tmp_path) -> None:
    settings = _settings(tmp_path)
    cache = MagicMock()
    cached_chunks = [{"video_id": "v1", "matched_text": "private", "relevance_score": 1.0}]
    cache.get.return_value = {"answer": {"chunks": cached_chunks}, "cache_type": "exact"}

    engine = AdaptiveHierarchicalMemoryEngine(
        settings=settings,
        repository=MagicMock(),
        store=MagicMock(),
        fts=MagicMock(),
        cache=cache,
    )

    with patch("app.services.ahme_engine.embed_query", return_value=[1.0, 0.0, 0.0]):
        hits, metrics = engine.retrieve("search my memory", user_id="tenant-123")

    assert hits == cached_chunks
    assert metrics.cache_hit is True
    assert cache.get.call_args.kwargs["user_id"] == "tenant-123"
