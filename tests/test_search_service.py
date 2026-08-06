"""Tests for search service grouping and repository search."""

from unittest.mock import patch

from app.config import Settings
from app.db.chroma_client import reset_chroma_cache
from app.db.repositories.memory_repository import MemoryRepository
from app.services.search_service import SearchService, _group_by_video
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
