"""Integration tests for UniversalMemoryService ingest pipeline."""

import pytest

from app.db.memory_store import MemoryStore
from app.models.capsule import MemoryCapsule, MemorySection
from app.models.lifecycle import MemoryLifecycleState
from app.models.reflection import ReflectionInput, SaveReason
from app.models.trust import VerificationStatus
from app.models.video import SourceType, VideoMetadata
from app.services.event_bus import EventBus
from app.services.universal_memory_service import UniversalMemoryService


@pytest.fixture
def memory_os(test_settings) -> UniversalMemoryService:
    return UniversalMemoryService(settings=test_settings)


def _metadata() -> VideoMetadata:
    return VideoMetadata(
        video_id="brainvid12345",
        title="Brain Test Video",
        description="Testing universal memory pipeline",
        channel="Test Channel",
        webpage_url="https://www.youtube.com/watch?v=brainvid12345",
    )


def _capsule() -> MemoryCapsule:
    return MemoryCapsule(
        video_id="brainvid12345",
        title="Brain Test Video",
        one_line_memory="Universal memory integration test",
        short_summary="Pipeline test summary",
        topics=["testing", "memory"],
        entities=["Python"],
        tools_or_components=["Docker"],
        procedures=["Run pytest"],
        claims=["Tests prevent regressions"],
        sections=[
            MemorySection(
                title="Setup",
                summary="Prepare environment",
                start_time=0.0,
                end_time=30.0,
                keywords=["pytest"],
            )
        ],
    )


class TestUniversalMemoryService:
    def test_begin_capture(self, memory_os: UniversalMemoryService, test_settings) -> None:
        memory = memory_os.begin_capture(
            user_id="user-a",
            source_type=SourceType.YOUTUBE,
            external_id="cap1",
            canonical_url="https://youtu.be/cap1",
            title="Capture Test",
            source_author="Author",
        )
        assert memory.lifecycle_state == MemoryLifecycleState.CAPTURED
        store = MemoryStore(test_settings)
        transitions = store.list_transitions(memory.memory_id)
        assert any(t.to_state == MemoryLifecycleState.CAPTURED for t in transitions)
        assert transitions[0].reason == "created"

    def test_finalize_ingest_full_pipeline(
        self, memory_os: UniversalMemoryService, test_settings
    ) -> None:
        metadata = _metadata()
        capsule = _capsule()
        reflection = ReflectionInput(
            save_reason=SaveReason.GOAL,
            goal="Build brain layer",
        )
        memory = memory_os.finalize_ingest(
            user_id="user-a",
            metadata=metadata,
            capsule=capsule,
            reflection=reflection,
            chunk_count=4,
            embedding_model="test-model",
            transcript_source="manual_captions",
            has_capsule=True,
        )
        assert memory.lifecycle_state in {
            MemoryLifecycleState.TRUSTED,
            MemoryLifecycleState.VERIFIED,
        }
        assert memory.verification_status in {
            VerificationStatus.VERIFIED,
            VerificationStatus.PARTIAL,
        }
        assert memory.trust is not None
        assert memory.trust.overall > 0
        assert memory.embedding_refs.chunk_count == 4
        assert memory.relationship_summary.get("concept", 0) >= 1

        store = MemoryStore(test_settings)
        transitions = store.list_transitions(memory.memory_id)
        states = {t.to_state for t in transitions}
        assert MemoryLifecycleState.ENRICHED in states
        assert MemoryLifecycleState.EMBEDDED in states
        assert MemoryLifecycleState.CONNECTED in states

        events, _ = EventBus(test_settings).list_events(
            user_id="user-a",
            event_type="ingest.completed",
        )
        assert len(events) == 1
        event = events[0]
        assert event.aggregate_type == "memory"
        assert event.aggregate_id == memory.memory_id
        assert event.actor == "system"
        assert event.payload == {
            "chunk_count": 4,
            "has_capsule": True,
            "lifecycle_state": memory.lifecycle_state.value,
            "source_type": SourceType.YOUTUBE.value,
            "verification_status": memory.verification_status.value,
        }
        persisted = str(event.payload)
        assert metadata.webpage_url not in persisted
        assert metadata.title not in persisted
        assert capsule.short_summary not in persisted
        assert reflection.goal not in persisted

    def test_mark_existing_indexed(self, memory_os: UniversalMemoryService, test_settings) -> None:
        private_url = "https://youtu.be/private-skip"
        private_title = "private skipped title"
        memory = memory_os.mark_existing_indexed(
            user_id="user-a",
            source_type=SourceType.YOUTUBE,
            external_id="skip1",
            canonical_url=private_url,
            title=private_title,
            source_author="private channel",
        )
        assert memory.lifecycle_state == MemoryLifecycleState.TRUSTED
        assert memory.trust is not None

        events, _ = EventBus(test_settings).list_events(
            user_id="user-a",
            event_type="ingest.skipped",
        )
        assert len(events) == 1
        event = events[0]
        assert event.aggregate_id == memory.memory_id
        assert event.payload == {
            "lifecycle_state": MemoryLifecycleState.TRUSTED.value,
            "reason": "already_indexed",
            "source_type": SourceType.YOUTUBE.value,
        }
        persisted = str(event.payload)
        assert private_url not in persisted
        assert private_title not in persisted
        assert "private channel" not in persisted
