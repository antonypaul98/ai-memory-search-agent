"""Acceptance regression for N-07 Learning Evolution."""

from unittest.mock import MagicMock

from app.config import Settings
from app.models.reflection import ReflectionDisplay, UsageStats
from app.services.search_service import SearchService


def test_usage_can_evolve_ranking_without_reingest_or_evidence_mutation(tmp_path) -> None:
    settings = Settings(
        sqlite_path=str(tmp_path / "learning-acceptance.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        chroma_collection_name="learning-acceptance",
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
        "learned-preference": UsageStats(),
    }
    registry.get_usage.side_effect = lambda video_id, user_id: usage[video_id]

    before = service.search("retrieval systems", limit=2, user_id="tenant-a")
    assert [item.video_id for item in before.results] == [
        "semantic-first",
        "learned-preference",
    ]

    # The same already-indexed memory later receives explicit positive usage feedback.
    # No capture/ingest path is invoked; only tenant-local usage metadata changes.
    usage["learned-preference"] = UsageStats(helpful_count=3)
    after = service.search("retrieval systems", limit=2, user_id="tenant-a")

    assert [item.video_id for item in after.results] == [
        "learned-preference",
        "semantic-first",
    ]
    learned = after.results[0]
    assert learned.relevance_score == 0.58
    assert learned.similarity_score == 0.58
    assert "learning:helpful" in learned.matching_metadata
    assert "Learned preference signals: helpful" in learned.why_matched

    # Learning is an additive ranking layer: it does not persist replacement
    # evidence, write a new memory, or alter the source retrieval score.
    assert repository.method_calls == []
    assert memory_store.method_calls == [
        call
        for call in memory_store.method_calls
        if call[0] == "get_by_external"
    ]
    assert service._ahme.retrieve.call_count == 2
    assert all(
        call.kwargs.get("user_id") == "tenant-a"
        for call in registry.get_usage.call_args_list
    )
