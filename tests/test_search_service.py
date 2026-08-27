"""Tests for search service grouping and repository search."""

from unittest.mock import MagicMock, patch

from app.config import Settings
from app.db.chroma_client import reset_chroma_cache
from app.db.repositories.memory_repository import MemoryRepository
from app.models.reflection import ReflectionDisplay, UsageStats
from app.services.search_service import (
    SearchService,
    _group_by_video,
    _reflection_alignment,
)
from app.utils.chunking import TranscriptChunk


def _store_sample_videos(settings: Settings) -> MemoryRepository:
    reset_chroma_cache()
    repo = MemoryRepository(settings)

    repo.upsert_chunks(
        video_id="video_a",
        url="https://www.youtube.com/watch?v=video_a",
        title="Protein Meals",
        channel="Chef A",
        thumbnail="https://img.example/a.jpg",
        duration=100.0,
        transcript_source="manual_captions",
        description="High protein meal prep ideas for busy weeks.",
        one_line_memory="Protein Meals — High protein meal prep ideas for busy weeks.",
        why_saved=["You saved content from Chef A, which may reflect interest in this creator's topics."],
        action_items=["Try prepping ingredients on Sunday for the week."],
        chunks=[
            TranscriptChunk(0, "high protein chicken bowl", 0.0, 5.0),
            TranscriptChunk(1, "meal prep sunday routine", 5.0, 10.0),
        ],
        embeddings=[[1.0, 0.0, 0.0], [0.9, 0.1, 0.0]],
        embedding_model="test-model",
    )
    repo.upsert_chunks(
        video_id="video_b",
        url="https://www.youtube.com/watch?v=video_b",
        title="Cardio Workout",
        channel="Coach B",
        thumbnail="https://img.example/b.jpg",
        duration=200.0,
        transcript_source="auto_generated",
        chunks=[
            TranscriptChunk(0, "running intervals for stamina", 0.0, 8.0),
        ],
        embeddings=[[0.0, 1.0, 0.0]],
        embedding_model="test-model",
    )
    return repo


class TestGroupByVideo:
    def test_keeps_best_scoring_chunk(self) -> None:
        hits = [
            {"video_id": "v1", "relevance_score": 0.5, "matched_text": "low"},
            {"video_id": "v1", "relevance_score": 0.9, "matched_text": "high"},
            {"video_id": "v2", "relevance_score": 0.7, "matched_text": "other"},
        ]
        grouped = _group_by_video(hits)
        assert grouped["v1"]["matched_text"] == "high"
        assert len(grouped) == 2


class TestReflectionAwareRanking:
    def test_alignment_is_small_deterministic_and_explainable(self) -> None:
        reflection = ReflectionDisplay(
            goal="Kubernetes certification",
            reflection_note="Use this for my cluster certification study plan",
            save_reason="future_learning",
        )
        bonus, signals = _reflection_alignment("kubernetes certification", reflection)

        assert 0 < bonus <= 0.075
        assert "goal" in signals
        assert "note" in signals

    def test_unrelated_reflection_does_not_change_ranking(self) -> None:
        reflection = ReflectionDisplay(
            goal="Learn bread baking",
            reflection_note="Weekend sourdough project",
            save_reason="project",
        )
        bonus, signals = _reflection_alignment("kubernetes certification", reflection)

        assert bonus == 0.0
        assert signals == []

    def test_tenant_local_goal_can_break_close_semantic_tie_without_mutating_similarity(
        self, tmp_path
    ) -> None:
        settings = Settings(
            sqlite_path=str(tmp_path / "reflection-ranking.db"),
            chroma_persist_dir=str(tmp_path / "chroma"),
            chroma_collection_name="reflection-ranking",
            jobs_enabled=False,
        )
        registry = MagicMock()
        repository = MagicMock()
        service = SearchService(settings=settings, repository=repository, registry=registry)
        service._yt_store = MagicMock()
        service._yt_store.get.return_value = None

        hits = [
            {
                "video_id": "semantic-first",
                "relevance_score": 0.60,
                "matched_text": "general certification preparation",
                "title": "Certification overview",
                "channel": "Channel A",
                "thumbnail": "",
                "url": "https://www.youtube.com/watch?v=semantic-first",
            },
            {
                "video_id": "goal-aligned",
                "relevance_score": 0.58,
                "matched_text": "kubernetes exam preparation",
                "title": "Kubernetes exam guide",
                "channel": "Channel B",
                "thumbnail": "",
                "url": "https://www.youtube.com/watch?v=goal-aligned",
            },
        ]
        service._ahme = MagicMock()
        service._ahme.retrieve.return_value = (hits, {})

        reflections = {
            "semantic-first": ReflectionDisplay(),
            "goal-aligned": ReflectionDisplay(
                goal="Kubernetes certification",
                reflection_note="",
                save_reason="future_learning",
            ),
        }
        registry.get_reflection.side_effect = lambda video_id, user_id: reflections[video_id]
        registry.get_usage.return_value = UsageStats()

        response = service.search(
            "kubernetes certification",
            limit=2,
            user_id="tenant-a",
        )

        assert [item.video_id for item in response.results] == [
            "goal-aligned",
            "semantic-first",
        ]
        # Personalization affects order only; evidence/similarity scores remain honest.
        assert response.results[0].relevance_score == 0.58
        assert response.results[0].similarity_score == 0.58
        assert "reflection:goal" in response.results[0].matching_metadata
        assert "Saved-context alignment: goal" in response.results[0].why_matched
        assert all(
            call.kwargs.get("user_id") == "tenant-a"
            for call in registry.get_reflection.call_args_list
        )


class TestSearchService:
    def test_search_returns_grouped_videos(self, tmp_path) -> None:
        settings = Settings(
            chroma_persist_dir=str(tmp_path / "chroma_search"),
            chroma_collection_name="search_test",
            search_top_k_chunks=10,
            search_top_k_videos=5,
        )
        repo = _store_sample_videos(settings)

        with patch(
            "app.services.ahme_engine.embed_query",
            return_value=[1.0, 0.0, 0.0],
        ):
            service = SearchService(settings=settings, repository=repo)
            response = service.search("protein meals", limit=2)

        assert response.query == "protein meals"
        assert len(response.results) >= 1
        top = response.results[0]
        assert top.video_id == "video_a"
        assert top.title == "Protein Meals"
        assert top.channel == "Chef A"
        assert top.matched_text
        assert top.relevance_score > 0
        assert "Transcript passage matched" in top.why_matched
        assert top.one_line_memory
        assert top.original_url
        assert top.timestamp_url
        assert "t=" in top.timestamp_url
        assert isinstance(top.why_saved, list)
        assert isinstance(top.action_items, list)

    def test_delete_item_removes_chunks(self, tmp_path) -> None:
        settings = Settings(
            chroma_persist_dir=str(tmp_path / "chroma_delete"),
            chroma_collection_name="delete_test",
        )
        repo = _store_sample_videos(settings)
        assert repo.check_connection()["document_count"] == 3
        repo.delete_item("video_a")
        assert repo.check_connection()["document_count"] == 1
