"""Regression coverage for tenant-scoped Memory Intelligence capsule reads."""

from __future__ import annotations

import inspect

from app.config import Settings
from app.models.capsule import MemoryCapsule
from app.services import memory_intelligence_service as service_module
from app.services.memory_intelligence_service import MemoryIntelligenceService


class RecordingArtifactStore:
    def __init__(self, payload: str | None) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def load_capsule_json(self, *, user_id: str, video_id: str) -> str | None:
        self.calls.append((user_id, video_id))
        return self.payload


def _settings(tmp_path) -> Settings:
    return Settings(
        chroma_persist_dir=str(tmp_path / "chroma"),
        chroma_collection_name="artifact_routing_test",
        sqlite_path=str(tmp_path / "videos.db"),
        hierarchical_retrieval_enabled=False,
        semantic_cache_enabled=False,
        jobs_enabled=False,
        auth_enabled=False,
        local_demo_mode=True,
        debug=True,
    )


def _capsule_json() -> str:
    return MemoryCapsule(
        video_id="video-1",
        title="Tenant capsule",
        creator="Creator",
        one_line_memory="Tenant scoped memory",
        short_summary="Tenant scoped capsule summary",
        topics=["RAG"],
        entities=[],
        tools_or_components=[],
        procedures=[],
        claims=[],
        sections=[],
    ).model_dump_json()


def test_capsule_load_forwards_exact_tenant_identity(tmp_path) -> None:
    artifacts = RecordingArtifactStore(_capsule_json())
    service = MemoryIntelligenceService(settings=_settings(tmp_path), artifact_store=artifacts)

    capsule = service._load_capsule_json(user_id="tenant-a", video_id="video-1")

    assert capsule is not None
    assert capsule.video_id == "video-1"
    assert artifacts.calls == [("tenant-a", "video-1")]


def test_invalid_capsule_payload_fails_closed(tmp_path) -> None:
    artifacts = RecordingArtifactStore("not-json")
    service = MemoryIntelligenceService(settings=_settings(tmp_path), artifact_store=artifacts)

    assert service._load_capsule_json(user_id="tenant-a", video_id="video-1") is None
    assert artifacts.calls == [("tenant-a", "video-1")]


def test_memory_intelligence_has_no_direct_capsule_sqlite_table_read() -> None:
    source = inspect.getsource(service_module)
    assert "memory_capsules_json" not in source
