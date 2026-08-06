"""Tests for memory lifecycle state machine."""

import pytest

from app.db.memory_store import MemoryStore
from app.models.lifecycle import MemoryLifecycleState
from app.models.video import SourceType
from app.services.memory_lifecycle_service import (
    InvalidLifecycleTransitionError,
    MemoryLifecycleService,
)


@pytest.fixture
def lifecycle(test_settings) -> MemoryLifecycleService:
    store = MemoryStore(test_settings)
    return MemoryLifecycleService(store=store)


def _create(store: MemoryStore, external_id: str = "lc1"):
    return store.upsert(
        user_id="user-a",
        source_type=SourceType.YOUTUBE,
        external_id=external_id,
        canonical_url=f"https://youtu.be/{external_id}",
        title="Lifecycle",
        lifecycle_state=MemoryLifecycleState.CAPTURED,
    )


class TestMemoryLifecycle:
    def test_advance_ingest_pipeline(self, lifecycle: MemoryLifecycleService, test_settings) -> None:
        store = MemoryStore(test_settings)
        memory = _create(store)
        updated = lifecycle.advance_pipeline(
            memory_id=memory.memory_id,
            user_id="user-a",
            target_state=MemoryLifecycleState.TRUSTED,
            reason="test_pipeline",
        )
        assert updated.lifecycle_state == MemoryLifecycleState.TRUSTED
        transitions = store.list_transitions(memory.memory_id)
        states = [t.to_state for t in transitions]
        assert MemoryLifecycleState.PARSED in states
        assert MemoryLifecycleState.EMBEDDED in states
        assert MemoryLifecycleState.CONNECTED in states
        assert MemoryLifecycleState.TRUSTED in states

    def test_invalid_transition_rejected(self, lifecycle: MemoryLifecycleService, test_settings) -> None:
        store = MemoryStore(test_settings)
        memory = _create(store)
        with pytest.raises(InvalidLifecycleTransitionError):
            lifecycle.transition(
                memory_id=memory.memory_id,
                user_id="user-a",
                to_state=MemoryLifecycleState.TRUSTED,
                reason="skip_steps",
            )

    def test_archive_and_revive(self, lifecycle: MemoryLifecycleService, test_settings) -> None:
        store = MemoryStore(test_settings)
        memory = _create(store, external_id="arch1")
        lifecycle.advance_pipeline(
            memory_id=memory.memory_id,
            user_id="user-a",
            target_state=MemoryLifecycleState.VERIFIED,
        )
        archived = lifecycle.archive(memory_id=memory.memory_id, user_id="user-a")
        assert archived.lifecycle_state == MemoryLifecycleState.ARCHIVED
        revived = lifecycle.revive(memory_id=memory.memory_id, user_id="user-a")
        assert revived.lifecycle_state == MemoryLifecycleState.REVIVED

    def test_merge_from_trusted(self, lifecycle: MemoryLifecycleService, test_settings) -> None:
        store = MemoryStore(test_settings)
        primary = _create(store, external_id="merge_primary")
        duplicate = _create(store, external_id="merge_dup")
        lifecycle.advance_pipeline(
            memory_id=primary.memory_id,
            user_id="user-a",
            target_state=MemoryLifecycleState.TRUSTED,
        )
        lifecycle.advance_pipeline(
            memory_id=duplicate.memory_id,
            user_id="user-a",
            target_state=MemoryLifecycleState.TRUSTED,
        )
        merged = lifecycle.merge(
            memory_id=duplicate.memory_id,
            user_id="user-a",
            into_memory_id=primary.memory_id,
            reason="dedup",
        )
        assert merged.lifecycle_state == MemoryLifecycleState.MERGED
        transitions = store.list_transitions(duplicate.memory_id)
        assert transitions[-1].to_state == MemoryLifecycleState.MERGED
