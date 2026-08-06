"""Tests for V1-3 Memory Intelligence Layer."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.intelligence_store import IntelligenceStore
from app.db.schema import SCHEMA_VERSION, migrate
from app.db.youtube_memory_store import YouTubeMemoryStore, new_memory_id
from app.main import app
from app.models.capsule import MemoryCapsule
from app.models.intelligence import LearningRelation, TimelineMode, TopicCategory
from app.models.user import LOCAL_DEFAULT_USER_ID, UserPublic
from app.models.video import SourceType, VideoMetadata
from app.models.youtube_memory import YouTubeMemory
from app.services.memory_intelligence_service import MemoryIntelligenceService
from app.services.sources.base_source import ProcessingStatus


@pytest.fixture
def intel_settings(tmp_path) -> Settings:
    return Settings(
        chroma_persist_dir=str(tmp_path / "chroma"),
        chroma_collection_name="intel_test",
        sqlite_path=str(tmp_path / "videos.db"),
        hierarchical_retrieval_enabled=False,
        semantic_cache_enabled=False,
        jobs_enabled=False,
        auth_enabled=False,
        local_demo_mode=True,
        debug=True,
    )


def _capsule(video_id: str, *, topics: list[str], title: str = "Demo") -> MemoryCapsule:
    return MemoryCapsule(
        video_id=video_id,
        title=title,
        creator="Demo Channel",
        one_line_memory=f"About {', '.join(topics)}",
        short_summary=f"Introduction to {topics[0] if topics else 'tech'}",
        topics=topics,
        entities=topics[:1],
        tools_or_components=[],
        procedures=[],
        claims=[],
        sections=[],
    )


def _yt_memory(
    settings: Settings,
    *,
    video_id: str,
    title: str,
    channel: str = "Demo Channel",
    topics_hint: str = "",
) -> YouTubeMemory:
    now = datetime.now(timezone.utc).isoformat()
    mem = YouTubeMemory(
        memory_id=new_memory_id(),
        user_id=LOCAL_DEFAULT_USER_ID,
        video_id=video_id,
        url=f"https://www.youtube.com/watch?v={video_id}",
        title=title,
        description=topics_hint,
        channel=channel,
        duration_sec=900.0,
        saved_at=now,
        processing_status=ProcessingStatus.COMPLETED,
        updated_at=now,
    )
    YouTubeMemoryStore(settings).upsert(mem)
    return mem


def _index(
    service: MemoryIntelligenceService,
    settings: Settings,
    *,
    video_id: str,
    title: str,
    topics: list[str],
    channel: str = "Demo Channel",
) -> None:
    _yt_memory(settings, video_id=video_id, title=title, channel=channel, topics_hint=" ".join(topics))
    meta = VideoMetadata(
        video_id=video_id,
        title=title,
        description=" ".join(topics),
        channel=channel,
        webpage_url=f"https://www.youtube.com/watch?v={video_id}",
        source_type=SourceType.YOUTUBE,
        duration=900.0,
    )
    service.on_memory_indexed(
        user_id=LOCAL_DEFAULT_USER_ID,
        metadata=meta,
        capsule=_capsule(video_id, topics=topics, title=title),
    )


class TestSchemaV7:
    def test_migrates_to_v7(self, intel_settings: Settings) -> None:
        migrate(intel_settings)
        assert SCHEMA_VERSION >= 7
        store = IntelligenceStore(intel_settings)
        store.upsert_topic(
            user_id=LOCAL_DEFAULT_USER_ID,
            name="RAG",
            category=TopicCategory.TECHNOLOGY,
            evidence="test",
            video_id="abc12345678",
        )
        topics = store.list_topics(LOCAL_DEFAULT_USER_ID)
        assert any(t.normalized_name == "rag" for t in topics)


class TestTopicDiscovery:
    def test_incremental_topics_and_capsules(self, intel_settings: Settings) -> None:
        service = MemoryIntelligenceService(settings=intel_settings)
        _index(service, intel_settings, video_id="vidrag00001", title="RAG intro", topics=["RAG", "embeddings"])
        _index(service, intel_settings, video_id="vidrag00002", title="Advanced RAG", topics=["RAG", "reranking"])

        topics = service.list_topics(user_id=LOCAL_DEFAULT_USER_ID)
        rag = next(t for t in topics.topics if t.normalized_name == "rag")
        assert rag.memory_count == 2
        assert len(rag.evidence) >= 1

        capsules = service.list_capsules(user_id=LOCAL_DEFAULT_USER_ID)
        assert any(c.normalized_name == "rag" for c in capsules.capsules)
        capsule = next(c for c in capsules.capsules if c.normalized_name == "rag")
        assert capsule.memory_count >= 2
        assert capsule.summary


class TestLearningGraphAndRoadmap:
    def test_edges_and_roadmap(self, intel_settings: Settings) -> None:
        service = MemoryIntelligenceService(settings=intel_settings)
        _index(
            service,
            intel_settings,
            video_id="vidmcp00001",
            title="MCP beginner tutorial",
            topics=["MCP"],
        )
        _index(
            service,
            intel_settings,
            video_id="vidmcp00002",
            title="MCP advanced deep dive",
            topics=["MCP"],
        )

        graph = service.learning_graph(user_id=LOCAL_DEFAULT_USER_ID, topic="MCP")
        assert graph.node_count >= 2
        assert any(e.relation == LearningRelation.SAME_TOPIC for e in graph.edges)
        assert all(e.evidence for e in graph.edges)

        road = service.roadmap("MCP", user_id=LOCAL_DEFAULT_USER_ID)
        assert road.topic.lower() == "mcp"
        assert road.recommended_order
        assert set(road.already_completed) == set(road.recommended_order)
        assert road.evidence_only is True


class TestTimelineCreatorsInsights:
    def test_timeline_creators_insights(self, intel_settings: Settings) -> None:
        service = MemoryIntelligenceService(settings=intel_settings)
        _index(service, intel_settings, video_id="vidk8s000001", title="Kubernetes basics", topics=["Kubernetes"])
        _index(
            service,
            intel_settings,
            video_id="vidpy0000001",
            title="Python for beginners",
            topics=["Python"],
            channel="Other Creator",
        )

        tl = service.timeline(user_id=LOCAL_DEFAULT_USER_ID, mode=TimelineMode.RECENTLY_SAVED)
        assert len(tl.entries) >= 2
        assert all(e.reason for e in tl.entries)

        creators = service.list_creators(user_id=LOCAL_DEFAULT_USER_ID)
        assert creators.total >= 1
        assert all(c.evidence for c in creators.creators)

        insights = service.insights(user_id=LOCAL_DEFAULT_USER_ID)
        assert insights.total_memories >= 2
        assert insights.total_topics >= 1
        assert insights.top_topics


class TestDuplicateKnowledge:
    def test_shared_topic_diversity(self, intel_settings: Settings) -> None:
        service = MemoryIntelligenceService(settings=intel_settings)
        _index(service, intel_settings, video_id="viddup000001", title="Docker tutorial basics", topics=["Docker"])
        _index(service, intel_settings, video_id="viddup000002", title="Docker tutorial advanced", topics=["Docker"])
        dupes = service.duplicate_knowledge(user_id=LOCAL_DEFAULT_USER_ID)
        assert dupes.items
        assert all(0 <= i.diversity_score <= 1 for i in dupes.items)
        assert all(i.evidence for i in dupes.items)


class TestRetrieveExplainability:
    def test_retrieve_requires_explanation(self, intel_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.models.video import SearchResponse, SearchResultItem
        from app.models.reflection import ReflectionDisplay, UsageStats

        service = MemoryIntelligenceService(settings=intel_settings)
        _index(service, intel_settings, video_id="vidret000001", title="Local models guide", topics=["LLM"])

        fake = SearchResponse(
            query="local models",
            results=[
                SearchResultItem(
                    video_id="vidret000001",
                    title="Local models guide",
                    channel="Demo Channel",
                    thumbnail="",
                    url="https://www.youtube.com/watch?v=vidret000001",
                    original_url="https://www.youtube.com/watch?v=vidret000001",
                    timestamp_url="https://www.youtube.com/watch?v=vidret000001&t=0s",
                    matched_text="running local models on your machine",
                    relevance_score=0.82,
                    why_matched="Matched transcript about local models",
                    reflection=ReflectionDisplay(),
                    usage=UsageStats(),
                    confidence=0.82,
                )
            ],
        )
        monkeypatch.setattr(service._search, "search", lambda *a, **k: fake)

        result = service.retrieve("the long video about local models", user_id=LOCAL_DEFAULT_USER_ID)
        assert result.search_path
        assert result.results
        hit = result.results[0]
        assert hit.explanation.why
        assert hit.explanation.search_path
        assert hit.explanation.confidence >= 0
        assert "LLM" in hit.explanation.matched_entities or hit.explanation.evidence_refs


class TestIntelligenceAPI:
    def test_endpoints(self, intel_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.api import auth as auth_mod
        from app.config import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("SQLITE_PATH", intel_settings.sqlite_path)
        monkeypatch.setenv("CHROMA_PERSIST_DIR", intel_settings.chroma_persist_dir)

        # Bind settings via dependency override
        app.dependency_overrides[get_settings] = lambda: intel_settings
        app.dependency_overrides[auth_mod.get_current_user] = lambda: UserPublic(
            user_id=LOCAL_DEFAULT_USER_ID, display_name="Demo"
        )

        service = MemoryIntelligenceService(settings=intel_settings)
        _index(service, intel_settings, video_id="vidapi000001", title="Intro to RAG", topics=["RAG"])

        client = TestClient(app)
        assert client.get("/api/v1/intelligence/topics").status_code == 200
        assert client.get("/api/v1/intelligence/timeline").status_code == 200
        assert client.get("/api/v1/intelligence/learning-graph").status_code == 200
        assert client.get("/api/v1/intelligence/roadmap", params={"topic": "RAG"}).status_code == 200
        assert client.get("/api/v1/intelligence/capsules").status_code == 200
        assert client.get("/api/v1/intelligence/duplicates").status_code == 200
        assert client.get("/api/v1/intelligence/creators").status_code == 200
        assert client.get("/api/v1/intelligence/insights").status_code == 200

        # retrieve with mocked search
        from app.models.video import SearchResponse

        monkeypatch.setattr(
            MemoryIntelligenceService,
            "retrieve",
            lambda self, *a, **k: __import__(
                "app.models.intelligence", fromlist=["NaturalRetrieveResponse"]
            ).NaturalRetrieveResponse(query="RAG", results=[], search_path=["ahme_hybrid_retrieve"]),
        )
        assert client.get("/api/v1/intelligence/retrieve", params={"q": "RAG"}).status_code == 200

        app.dependency_overrides.clear()
        get_settings.cache_clear()


class TestPerformanceBenchmark:
    def test_topic_list_latency(self, intel_settings: Settings, benchmark=None) -> None:
        service = MemoryIntelligenceService(settings=intel_settings)
        for i in range(15):
            _index(
                service,
                intel_settings,
                video_id=f"vidbench{i:04d}",
                title=f"Topic video {i}",
                topics=["RAG", f"Concept{i % 5}"],
            )
        import time

        started = time.perf_counter()
        topics = service.list_topics(user_id=LOCAL_DEFAULT_USER_ID, limit=50)
        insights = service.insights(user_id=LOCAL_DEFAULT_USER_ID)
        elapsed_ms = (time.perf_counter() - started) * 1000
        assert topics.total >= 1
        assert insights.total_memories >= 15
        # Aggregation over small corpus should be snappy
        assert elapsed_ms < 2000
