"""Exercise actual hierarchical storage deletion, not only the privacy helper."""
import os
import sqlite3
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.hierarchical_store import HierarchicalStore
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.models.capsule import MemoryCapsule, MemorySection
from app.models.video import SourceType
from app.services.privacy_service import PrivacyService


def seed(store, user_id):
    store.upsert_capsule(MemoryCapsule(video_id="shared", title="Evidence"), [1.0, 0.0], user_id=user_id)
    store.upsert_sections("shared", [MemorySection(title="Evidence")], [[1.0, 0.0]], user_id=user_id)


def test_legacy_delete_never_removes_vectors_with_a_known_owner(tmp_path):
    store = HierarchicalStore(Settings(_env_file=None, chroma_persist_dir=str(tmp_path / "chroma")))
    for owner in (None, "alice", "bob"):
        seed(store, owner)
    store.delete_video("shared", user_id="alice")
    store.delete_video("shared")
    for name in (store._settings.capsule_collection_name, store._settings.section_collection_name):
        rows = store._collection(name).get(include=["metadatas"])
        assert len(rows["ids"]) == 1
        assert rows["metadatas"][0]["user_id"] == "bob"


@pytest.mark.parametrize("fail_collection", ["capsules", "sections"])
def test_postgres_privacy_retains_ownership_after_real_vector_delete_failure(monkeypatch, tmp_path, fail_collection):
    if not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"):
        pytest.skip("real Postgres DSN required")
    settings = Settings(
        _env_file=None,
        **{field: "postgres" for field in RELATIONAL_STORE_BACKEND_FIELDS},
        postgres_dsn_env="MEMORY_AGENT_TEST_POSTGRES_DSN",
        sqlite_path=str(tmp_path / "forbidden.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        jobs_enabled=False,
    )
    attempts = []
    def reject_sqlite(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("unexpected relational SQLite connection")
    monkeypatch.setattr(sqlite3, "connect", reject_sqlite)
    privacy = PrivacyService(settings)
    owner, other = "delete-" + uuid4().hex, "delete-" + uuid4().hex
    memories = {}
    for tenant in (owner, other):
        memories[tenant] = privacy._memory_store.upsert(
            user_id=tenant, source_type=SourceType.WEB, external_id="shared",
            canonical_url="https://example.test/shared", title="Evidence",
        )
        privacy._registry.upsert_video(user_id=tenant, video_id="shared",
                                      url="https://example.test/shared", title="Evidence", channel="")
        seed(privacy._hstore, tenant)
    collection_type = type(privacy._hstore._collection(settings.capsule_collection_name))
    original_delete = collection_type.delete
    failed_name = settings.capsule_collection_name if fail_collection == "capsules" else settings.section_collection_name
    def fail_delete(self, *args, **kwargs):
        if self.name == failed_name:
            raise RuntimeError("injected vector backend failure")
        return original_delete(self, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(collection_type, "delete", fail_delete)
        with pytest.raises(RuntimeError, match="Hierarchical vector deletion failed"):
            privacy.delete_memory(memory_id=memories[owner].memory_id, user_id=owner)
    assert privacy._memory_store.get(memories[owner].memory_id, user_id=owner)
    assert privacy._memory_store.get(memories[other].memory_id, user_id=other)
    assert privacy.delete_memory(memory_id=memories[owner].memory_id, user_id=owner)["deleted"]
    assert privacy._memory_store.get(memories[owner].memory_id, user_id=owner) is None
    for name in (settings.capsule_collection_name, settings.section_collection_name):
        rows = privacy._hstore._collection(name).get(include=["metadatas"])
        assert len(rows["ids"]) == 1
        assert rows["metadatas"][0]["user_id"] == other
    assert attempts == []
    assert not (tmp_path / "forbidden.db").exists()


@pytest.mark.parametrize("owner", ["", "  "])
def test_blank_owner_cannot_turn_delete_into_unscoped_cleanup(tmp_path, owner):
    store = HierarchicalStore(Settings(_env_file=None, chroma_persist_dir=str(tmp_path / "chroma")))
    with pytest.raises(ValueError, match="user_id"):
        store.delete_video("shared", user_id=owner)
