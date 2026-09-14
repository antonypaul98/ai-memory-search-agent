from types import SimpleNamespace

from app.db.hierarchical_store import HierarchicalStore


class _Collection:
    def __init__(self):
        self.query_kwargs = None
        self.delete_kwargs = None

    def count(self):
        return 2

    def query(self, **kwargs):
        self.query_kwargs = kwargs
        return {
            "documents": [["owner document"]],
            "metadatas": [[{
                "video_id": "shared-video",
                "level": "capsule",
                "doc_id": "capsule_owner_shared-video",
                "title": "Owner",
                "user_id": "owner",
            }]],
            "distances": [[0.1]],
        }

    def delete(self, **kwargs):
        self.delete_kwargs = kwargs


class _Client:
    def __init__(self, collection):
        self.collection = collection

    def get_or_create_collection(self, *, name):
        return self.collection


def _store(collection):
    store = HierarchicalStore.__new__(HierarchicalStore)
    store._settings = SimpleNamespace(
        capsule_collection_name="capsules",
        section_collection_name="sections",
        chroma_collection_name="evidence",
    )
    store._client = _Client(collection)
    return store


def test_tenant_scoped_ids_do_not_collide_for_shared_video():
    assert HierarchicalStore._doc_id("capsule", "shared-video", user_id="alice") != HierarchicalStore._doc_id(
        "capsule", "shared-video", user_id="bob"
    )
    assert HierarchicalStore._doc_id("section", "shared-video", user_id="alice", index=0) != HierarchicalStore._doc_id(
        "section", "shared-video", user_id="bob", index=0
    )


def test_search_level_combines_tenant_and_video_filters():
    collection = _Collection()
    store = _store(collection)

    hits = store.search_level(
        "capsules",
        [0.1, 0.2],
        top_k=4,
        video_ids=["shared-video"],
        user_id="owner",
    )

    assert collection.query_kwargs["where"] == {
        "$and": [
            {"user_id": "owner"},
            {"video_id": {"$in": ["shared-video"]}},
        ]
    }
    assert hits[0]["user_id"] == "owner"


def test_delete_video_is_tenant_scoped_when_owner_is_known():
    collection = _Collection()
    store = _store(collection)

    store.delete_video("shared-video", user_id="owner")

    assert collection.delete_kwargs == {
        "where": {
            "$and": [
                {"user_id": "owner"},
                {"video_id": "shared-video"},
            ]
        }
    }
