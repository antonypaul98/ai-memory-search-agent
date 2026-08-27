"""Regression tests for N-07 deterministic Learning Evolution."""

from unittest.mock import MagicMock

from app.config import Settings
from app.models.reflection import ReflectionDisplay, UsageStats
from app.services.learning_evolution_service import usage_learning_signal
from app.services.search_service import SearchService


def test_usage_signal_rewards_helpful_and_caps_adjustment() -> None:
    adjustment, signals = usage_learning_signal(
        UsageStats(helpful_count=100, not_helpful_count=0, view_count=100)
    )

    assert adjustment == 0.04
    assert signals == ["helpful", "viewed"]


def test_usage_signal_penalizes_negative_feedback() -> None:
    adjustment, signals = usage_learning_signal(
        UsageStats(helpful_count=0, not_helpful_count=5, view_count=0)
    )

    assert adjustment == -0.03
    assert signals == ["not_helpful"]


def test_search_counts_do_not_create_self_reinforcing_learning_loop() -> None:
    low, low_signals = usage_learning_signal(UsageStats(search_count=1))
    high, high_signals = usage_learning_signal(UsageStats(search_count=10_000))

    assert low == high == 0.0
    assert low_signals == high_signals == []


def test_tenant_local_feedback_can_break_close_tie_without_mutating_evidence_score(
    tmp_path,
) -> None:
    settings = Settings(
        sqlite_path=str(tmp_path / "learning.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        chroma_collection_name="learning-evolution",
        jobs_enabled=False,
    )
    registry = MagicMock()
    repository = MagicMock()
    memory_store = MagicMock()
    memory_store.get_by_external.return_value = None
    service = SearchService(
        settings=settings,
        repository=repository,
        registry=registry,
        memory_store=memory_store,
    )
    service._yt_store = MagicMock()
    service._yt_store.get.return_value = None
    service._ahme = MagicMock()
    service._ahme.retrieve.return_value = (
        [
            {
                "video_id": "semantic-first",
                "relevance_score": 0.60,
                "matched_text": "general retrieval systems",
                "title": "Retrieval overview",
                "channel": "A",
                "thumbnail": "",
                "url": "https://www.youtube.com/watch?v=semantic-first",
            },
            {
                "video_id": "learned-preference",
                "relevance_score": 0.58,
                "matched_text": "retrieval system design",
                "title": "Retrieval design",
                "channel": "B",
                "thumbnail": "",
                "url": "https://www.youtube.com/watch?v=learned-preference",
            },
        ],
        {},
    )
    registry.get_reflection.return_value = ReflectionDisplay()
    usage = {
        "semantic-first": UsageStats(),
        "learned-preference": UsageStats(helpful_count=3),
    }
    registry.get_usage.side_effect = lambda video_id, user_id: usage[video_id]

    response = service.search("retrieval systems", limit=2, user_id="tenant-a")

    assert [item.video_id for item in response.results] == [
        "learned-preference",
        "semantic-first",
    ]
    # Learning changes ordering only; evidence scores stay auditable and untouched.
    assert response.results[0].relevance_score == 0.58
    assert response.results[0].similarity_score == 0.58
    assert "learning:helpful" in response.results[0].matching_metadata
    assert "Learned preference signals: helpful" in response.results[0].why_matched
    assert all(
        call.kwargs.get("user_id") == "tenant-a"
        for call in registry.get_usage.call_args_list
    )


def test_learning_metadata_failure_does_not_break_core_search(tmp_path) -> None:
    settings = Settings(
        sqlite_path=str(tmp_path / "learning-fail-open.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        chroma_collection_name="learning-fail-open",
        jobs_enabled=False,
    )
    registry = MagicMock()
    repository = MagicMock()
    memory_store = MagicMock()
    memory_store.get_by_external.return_value = None
    service = SearchService(
        settings=settings,
        repository=repository,
        registry=registry,
        memory_store=memory_store,
    )
    service._yt_store = MagicMock()
    service._yt_store.get.return_value = None
    service._ahme = MagicMock()
    service._ahme.retrieve.return_value = (
        [
            {
                "video_id": "v1",
                "relevance_score": 0.71,
                "matched_text": "memory retrieval",
                "title": "Memory retrieval",
                "channel": "A",
                "thumbnail": "",
                "url": "https://www.youtube.com/watch?v=v1",
            }
        ],
        {},
    )
    registry.get_reflection.return_value = ReflectionDisplay()
    # First usage lookup is the ranking signal and fails; the result rendering lookup
    # succeeds, proving learning metadata is additive rather than required for search.
    registry.get_usage.side_effect = [RuntimeError("analytics unavailable"), UsageStats()]

    response = service.search("memory retrieval", user_id="tenant-a")

    assert len(response.results) == 1
    assert response.results[0].video_id == "v1"
    assert response.results[0].relevance_score == 0.71
