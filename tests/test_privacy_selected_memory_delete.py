from __future__ import annotations

import inspect

import pytest

from app.config import Settings
from app.db.memory_privacy import delete_canonical_memory
from app.db.memory_store import MemoryStore
from app.db.postgres_memory_store import PostgresMemoryStore
from app.models.video import SourceType
from app.services.privacy_service import PrivacyService


def test_sqlite_canonical_delete_is_exact_tenant_scoped(tmp_path):
    settings = Settings(sqlite_path=str(tmp_path / "canonical-delete.db"))
    store = MemoryStore(settings)
    memory = store.upsert(
        user_id="tenant-a",
        source_type=SourceType.WEB,
        external_id="canonical-delete-1",
        canonical_url="https://example.com/canonical-delete-1",
        title="Canonical delete",
    )

    assert delete_canonical_memory(
        store,
        memory_id=memory.memory_id,
        user_id="tenant-b",
    ) is False
    assert store.get(memory.memory_id, user_id="tenant-a") is not None

    assert delete_canonical_memory(
        store,
        memory_id=memory.memory_id,
        user_id="tenant-a",
    ) is True
    assert store.get(memory.memory_id, user_id="tenant-a") is None
    assert store.list_transitions(memory.memory_id) == []


def test_postgres_canonical_delete_uses_exact_tenant_predicate():
    calls: list[tuple[str, tuple[str, str]]] = []

    class Cursor:
        rowcount = 1

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params):
            calls.append((" ".join(sql.split()), params))
            return Cursor()

    store = object.__new__(PostgresMemoryStore)
    store._connect = lambda: Connection()

    assert delete_canonical_memory(
        store,
        memory_id="memory-1",
        user_id="tenant-a",
    ) is True
    assert calls == [
        (
            "DELETE FROM memory_records WHERE memory_id = %s AND user_id = %s",
            ("memory-1", "tenant-a"),
        )
    ]


def test_unknown_canonical_memory_store_fails_closed():
    with pytest.raises(TypeError, match="Unsupported canonical memory store"):
        delete_canonical_memory(object(), memory_id="memory-1", user_id="tenant-a")


def test_legacy_sqlite_residual_cleanup_is_removed_from_privacy_service():
    source = inspect.getsource(PrivacyService)
    assert not hasattr(PrivacyService, "_delete_sqlite_memory_rows")
    for table in (
        "memory_records",
        "memory_lifecycle_events",
        "memory_versions",
        "memory_trust_history",
    ):
        assert table not in source
