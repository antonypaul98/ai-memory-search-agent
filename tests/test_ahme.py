"""Tests for Adaptive Hierarchical Memory Engine components."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings
from app.db.chroma_client import reset_chroma_cache
from app.db.repositories.memory_repository import MemoryRepository
from app.db.schema import bump_index_version, get_index_version, migrate
from app.models.capsule import MemoryCapsule, MemorySection
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.models.video import VideoMetadata
from app.services.ahme_engine import AdaptiveHierarchicalMemoryEngine
from app.services.capsule_service import build_capsule_deterministic, build_capsule_with_optional_llm
from app.services.deduplication_service import dedupe_chunk_texts, hash_text, is_near_duplicate, simhash64
from app.services.fts_index import FTSIndex
from app.services.grounded_synthesis import synthesize_grounded_answer
from app.services.mmr import mmr_select
from app.services.query_router import QueryType, route_query
from app.services.rrf import reciprocal_rank_fusion
from app.services.semantic_cache import SemanticCache, normalize_question
from app.utils.chunking import TranscriptChunk


def _sample_metadata() -> VideoMetadata:
    return VideoMetadata(
        video_id="vid_test",
        title="Build a PC",
        description="PC build guide with components and safety tips.",
        channel="Tech Channel",
        thumbnail="https://img.example/t.jpg",
        duration=600.0,
        webpage_url="https://www.youtube.com/watch?v=vid_test",
    )


def _sample_transcript() -> TranscriptResult:
    segments = [
        TranscriptSegment(text="First install the CPU on the motherboard.", start_time_sec=0.0, duration_sec=5.0),
        TranscriptSegment(text="Next connect the power supply cables carefully.", start_time_sec=5.0, duration_sec=6.0),
        TranscriptSegment(text="Make sure the GPU fits in the case.", start_time_sec=11.0, duration_sec=5.0),
    ]
    return TranscriptResult(
        video_id="vid_test",
        canonical_url="https://www.youtube.com/watch?v=vid_test",
        segments=segments,
        full_text=" ".join(s.text for s in segments),
        is_generated=False,
    )


class TestMemoryCapsule:
    def test_deterministic_capsule_validation(self) -> None:
        capsule = build_capsule_deterministic(
            metadata=_sample_metadata(),
            transcript=_sample_transcript(),
        )
        assert capsule.video_id == "vid_test"
        assert capsule.title == "Build a PC"
        assert capsule.one_line_memory
        assert capsule.topics
        assert capsule.sections

    def test_malformed_llm_response_fallback(self) -> None:
        provider = MagicMock()
        provider.generate_capsule_json.return_value = "not json at all"
        with patch("app.services.llm_provider.get_llm_provider", return_value=provider):
            capsule = build_capsule_with_optional_llm(
                metadata=_sample_metadata(),
                transcript=_sample_transcript(),
            )
        assert isinstance(capsule, MemoryCapsule)
        assert capsule.video_id == "vid_test"


class TestHybridRetrieval:
    def test_rrf_combines_rankings(self) -> None:
        fused = reciprocal_rank_fusion([["a", "b"], ["b", "c"]], k=60)
        scores = dict(fused)
        assert scores["b"] > scores["a"]
        assert scores["b"] > scores["c"]

    def test_mmr_reduces_redundancy(self) -> None:
        candidates = [
            {"matched_text": "install the cpu on motherboard carefully", "relevance_score": 0.9},
            {"matched_text": "install the cpu on motherboard safely", "relevance_score": 0.88},
            {"matched_text": "connect the power supply cables", "relevance_score": 0.7},
        ]
        selected = mmr_select(candidates, limit=2, lambda_=0.7)
        texts = [c["matched_text"] for c in selected]
        assert any("power supply" in t for t in texts)

    def test_sqlite_fts_retrieval(self, tmp_path) -> None:
        settings = Settings(sqlite_path=str(tmp_path / "fts.db"))
        migrate(settings)
        fts = FTSIndex(settings)
        fts.upsert(
            video_id="v1",
            level="evidence",
            doc_id="ev1",
            title="GPU Setup",
            body="install the gpu driver before gaming",
        )
        hits = fts.search("gpu install", limit=5)
        assert hits
        assert hits[0]["video_id"] == "v1"


class TestQueryRouter:
    def test_procedural_routing(self) -> None:
        route = route_query("How do I install the GPU driver?")
        assert QueryType.PROCEDURAL in route.query_types
        assert route.needs_detailed_evidence

    def test_comparison_routing(self) -> None:
        route = route_query("Compare both videos about PC builds")
        assert QueryType.CROSS_VIDEO in route.query_types or QueryType.COMPARISON in route.query_types


class TestDeduplication:
    def test_exact_and_near_duplicate_detection(self) -> None:
        texts = [
            "Install the CPU on the motherboard carefully.",
            "Install the CPU on the motherboard carefully.",
            "Install the CPU on the motherboard safely.",
            "Connect the power supply cables.",
        ]
        kept, report = dedupe_chunk_texts(texts)
        assert len(kept) < len(texts)
        assert report.exact_duplicate_chunks_removed >= 1
        assert hash_text(texts[0]) == hash_text(texts[1])
        assert is_near_duplicate(simhash64(texts[0]), simhash64(texts[0]))


class TestSemanticCache:
    def test_cache_hit_and_invalidation(self, tmp_path) -> None:
        settings = Settings(
            sqlite_path=str(tmp_path / "cache.db"),
            semantic_cache_enabled=True,
            semantic_cache_similarity_threshold=0.5,
        )
        migrate(settings)
        cache = SemanticCache(settings)
        embedding = [1.0, 0.0, 0.0]
        cache.put(
            question="What GPU do I need?",
            query_embedding=embedding,
            answer={"chunks": [{"matched_text": "gpu"}]},
            query_type="exact_lookup",
        )
        hit = cache.get(
            question="What GPU do I need?",
            query_embedding=embedding,
            query_type="exact_lookup",
        )
        assert hit and hit["cache_type"] == "exact"

        bump_index_version(settings)
        miss = cache.get(
            question="What GPU do I need?",
            query_embedding=embedding,
            query_type="exact_lookup",
        )
        assert miss is None


class TestHierarchicalEngine:
    def _store_video(self, settings: Settings) -> MemoryRepository:
        reset_chroma_cache()
        repo = MemoryRepository(settings)
        repo.upsert_chunks(
            video_id="video_a",
            url="https://www.youtube.com/watch?v=video_a",
            title="Protein Meals",
            channel="Chef A",
            thumbnail="",
            duration=100.0,
            transcript_source="manual_captions",
            chunks=[TranscriptChunk(0, "high protein chicken bowl", 0.0, 5.0)],
            embeddings=[[1.0, 0.0, 0.0]],
            embedding_model="test-model",
        )
        return repo

    def test_flat_pipeline_fallback(self, tmp_path) -> None:
        settings = Settings(
            chroma_persist_dir=str(tmp_path / "chroma_flat"),
            chroma_collection_name="flat_test",
            hierarchical_retrieval_enabled=False,
        )
        repo = self._store_video(settings)
        engine = AdaptiveHierarchicalMemoryEngine(settings=settings, repository=repo)
        with patch("app.services.ahme_engine.embed_query", return_value=[1.0, 0.0, 0.0]):
            hits, metrics = engine.retrieve("protein", top_k=3)
        assert hits
        assert metrics.pipeline == "flat"

    def test_hierarchical_narrowing(self, tmp_path) -> None:
        settings = Settings(
            chroma_persist_dir=str(tmp_path / "chroma_h"),
            chroma_collection_name="h_evidence",
            capsule_collection_name="h_capsules",
            section_collection_name="h_sections",
            sqlite_path=str(tmp_path / "h.db"),
            hierarchical_retrieval_enabled=True,
        )
        repo = self._store_video(settings)
        from app.db.hierarchical_store import HierarchicalStore

        store = HierarchicalStore(settings)
        capsule = MemoryCapsule(
            video_id="video_a",
            title="Protein Meals",
            short_summary="High protein meal prep",
            topics=["protein", "meals"],
        )
        store.upsert_capsule(capsule, [1.0, 0.0, 0.0])
        store.upsert_sections(
            "video_a",
            [MemorySection(title="Intro", summary="meal prep intro", start_time=0, end_time=30)],
            [[0.9, 0.1, 0.0]],
        )
        fts = FTSIndex(settings)
        fts.upsert(
            video_id="video_a",
            level="evidence",
            doc_id="youtube_video_a_0",
            title="Protein Meals",
            body="high protein chicken bowl",
        )
        engine = AdaptiveHierarchicalMemoryEngine(
            settings=settings,
            repository=repo,
            store=store,
            fts=fts,
        )
        with patch("app.services.ahme_engine.embed_query", return_value=[1.0, 0.0, 0.0]):
            hits, metrics = engine.retrieve("protein chicken", top_k=3)
        assert hits
        assert metrics.pipeline == "hierarchical"
        assert metrics.videos_considered >= 1


class TestGroundedSynthesis:
    def test_deterministic_synthesis(self) -> None:
        chunks = [
            {
                "video_id": "v1",
                "matched_text": "Install the CPU on the motherboard first.",
                "relevance_score": 0.9,
            }
        ]
        answer, confidence, _ms = synthesize_grounded_answer(
            "How do I install the CPU?",
            chunks,
        )
        assert answer.answer
        assert confidence in {"high", "medium", "low"}


class TestStorageMigration:
    def test_schema_migration_v2(self, tmp_path) -> None:
        settings = Settings(sqlite_path=str(tmp_path / "migrate.db"))
        migrate(settings)
        from app.db.schema import get_connection

        with get_connection(settings) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "content_hashes" in tables
        assert "semantic_cache" in tables
        assert get_index_version(settings) == "1"