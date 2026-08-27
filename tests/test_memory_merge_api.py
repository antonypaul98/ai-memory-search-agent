"""Regression tests for explicit duplicate-memory merge approval and isolation."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.db.memory_store import MemoryStore
from app.models.lifecycle import MemoryLifecycleState
from app.models.user import LOCAL_DEFAULT_USER_ID
from app.models.video import SourceType
from app.services.memory_lifecycle_service import MemoryLifecycleService


def _create_memory(
    store: MemoryStore,
    *,
    external_id: str,
    user_id: str = LOCAL_DEFAULT_USER_ID,
):
    return store.upsert(
        user_id=user_id,
        source_type=SourceType.YOUTUBE,
        external_id=external_id,
        canonical_url=f"https://youtu.be/{external_id}",
        title=f"Memory {external_id}",
        lifecycle_state=MemoryLifecycleState.CAPTURED,
    )


def _trust(lifecycle: MemoryLifecycleService, memory_id: str, user_id: str) -> None:
    lifecycle.advance_pipeline(
        memory_id=memory_id,
        user_id=user_id,
        target_state=MemoryLifecycleState.TRUSTED,
        reason="test_ready_for_merge",
    )


def test_merge_requires_explicit_confirmation(
    client: TestClient, test_settings: Settings
) -> None:
    store = MemoryStore(test_settings)
    lifecycle = MemoryLifecycleService(test_settings, store=store)
    source = _create_memory(store, external_id="merge-source-no-confirm")
    target = _create_memory(store, external_id="merge-target-no-confirm")
    _trust(lifecycle, source.memory_id, LOCAL_DEFAULT_USER_ID)
    _trust(lifecycle, target.memory_id, LOCAL_DEFAULT_USER_ID)

    response = client.post(
        f"/api/v1/memories/{source.memory_id}/merge",
        json={"into_memory_id": target.memory_id, "confirm": False},
    )

    assert response.status_code == 409
    assert store.get(source.memory_id, user_id=LOCAL_DEFAULT_USER_ID).lifecycle_state == MemoryLifecycleState.TRUSTED


def test_merge_rejects_self_merge(client: TestClient, test_settings: Settings) -> None:
    store = MemoryStore(test_settings)
    lifecycle = MemoryLifecycleService(test_settings, store=store)
    source = _create_memory(store, external_id="merge-self")
    _trust(lifecycle, source.memory_id, LOCAL_DEFAULT_USER_ID)

    response = client.post(
        f"/api/v1/memories/{source.memory_id}/merge",
        json={"into_memory_id": source.memory_id, "confirm": True},
    )

    assert response.status_code == 400


def test_confirmed_merge_is_audited(client: TestClient, test_settings: Settings) -> None:
    store = MemoryStore(test_settings)
    lifecycle = MemoryLifecycleService(test_settings, store=store)
    source = _create_memory(store, external_id="merge-source")
    target = _create_memory(store, external_id="merge-target")
    _trust(lifecycle, source.memory_id, LOCAL_DEFAULT_USER_ID)
    _trust(lifecycle, target.memory_id, LOCAL_DEFAULT_USER_ID)

    response = client.post(
        f"/api/v1/memories/{source.memory_id}/merge",
        json={
            "into_memory_id": target.memory_id,
            "confirm": True,
            "reason": "duplicate_merge_test",
        },
    )

    assert response.status_code == 200
    assert response.json()["lifecycle_state"] == "merged"
    transitions = store.list_transitions(source.memory_id)
    assert transitions[-1].to_state == MemoryLifecycleState.MERGED
    assert transitions[-1].metadata["into_memory_id"] == target.memory_id
    assert transitions[-1].reason == "duplicate_merge_test"
    assert store.get(target.memory_id, user_id=LOCAL_DEFAULT_USER_ID).lifecycle_state == MemoryLifecycleState.TRUSTED


def test_merge_cannot_target_another_tenant(
    client: TestClient, test_settings: Settings
) -> None:
    store = MemoryStore(test_settings)
    lifecycle = MemoryLifecycleService(test_settings, store=store)
    source = _create_memory(store, external_id="tenant-source")
    target = _create_memory(store, external_id="tenant-target", user_id="other-user")
    _trust(lifecycle, source.memory_id, LOCAL_DEFAULT_USER_ID)
    _trust(lifecycle, target.memory_id, "other-user")

    response = client.post(
        f"/api/v1/memories/{source.memory_id}/merge",
        json={"into_memory_id": target.memory_id, "confirm": True},
    )

    assert response.status_code == 404
    assert store.get(source.memory_id, user_id=LOCAL_DEFAULT_USER_ID).lifecycle_state == MemoryLifecycleState.TRUSTED


def test_merge_rejects_untrusted_source(
    client: TestClient, test_settings: Settings
) -> None:
    store = MemoryStore(test_settings)
    lifecycle = MemoryLifecycleService(test_settings, store=store)
    source = _create_memory(store, external_id="captured-source")
    target = _create_memory(store, external_id="trusted-target")
    _trust(lifecycle, target.memory_id, LOCAL_DEFAULT_USER_ID)

    response = client.post(
        f"/api/v1/memories/{source.memory_id}/merge",
        json={"into_memory_id": target.memory_id, "confirm": True},
    )

    assert response.status_code == 409
    assert store.get(source.memory_id, user_id=LOCAL_DEFAULT_USER_ID).lifecycle_state == MemoryLifecycleState.CAPTURED
