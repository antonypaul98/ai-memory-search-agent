from types import SimpleNamespace

import pytest

from app.db.hierarchical_store import HierarchicalStore


class _Collection:
    def __init__(self, ids, metadatas):
        self._ids = list(ids)
        self._metadatas = list(metadatas)
        self.deleted_ids = []

    def get(self, **kwargs):
        return {"ids": list(self._ids), "metadatas": list(self._metadatas)}

    def delete(self, **kwargs):
        self.deleted_ids.extend(kwargs.get("ids") or [])


class _Client:
    def __init__(self, collections):
        self._collections = collections

    def get_or_create_collection(self, *, name):
        return self._collections[name]


def _store():
    capsules = _Collection(
        ["capsule_old", "capsule_alice", "capsule_blank"],
        [{"video_id": "v1"}, {"video_id": "v1", "user_id": "alice"}, {"video_id": "v2", "user_id": "  "}],
    )
    sections = _Collection(
        ["section_old", "section_bob"],
        [{"video_id": "v1"}, {"video_id": "v1", "user_id": "bob"}],
    )
    store = HierarchicalStore.__new__(HierarchicalStore)
    store._settings = SimpleNamespace(
        capsule_collection_name="capsules",
        section_collection_name="sections",
        chroma_collection_name="evidence",
    )
    store._client = _Client({"capsules": capsules, "sections": sections})
    return store, capsules, sections


def test_legacy_inventory_reports_only_vectors_without_tenant_ownership():
    store, _, _ = _store()

    assert store.legacy_unscoped_vector_ids() == {
        "capsules": ["capsule_old", "capsule_blank"],
        "sections": ["section_old"],
    }


def test_purge_requires_explicit_confirmation_and_preserves_scoped_vectors():
    store, capsules, sections = _store()

    with pytest.raises(ValueError, match="confirm=True"):
        store.purge_legacy_unscoped_vectors()

    assert capsules.deleted_ids == []
    assert sections.deleted_ids == []

    deleted = store.purge_legacy_unscoped_vectors(confirm=True)

    assert deleted == {"capsules": 2, "sections": 1}
    assert capsules.deleted_ids == ["capsule_old", "capsule_blank"]
    assert sections.deleted_ids == ["section_old"]
