from app.services.privacy_service import _delete_hierarchical_vectors


class _Store:
    def __init__(self):
        self.calls = []

    def delete_video(self, video_id, *, user_id=None):
        self.calls.append((video_id, user_id))


def test_shared_source_deletes_only_exact_tenant_vectors():
    store = _Store()

    _delete_hierarchical_vectors(
        store,
        external_id="shared-video",
        user_id="alice",
        shared_external_id=True,
    )

    assert store.calls == [("shared-video", "alice")]


def test_exclusive_source_also_purges_unscoped_legacy_vectors():
    store = _Store()

    _delete_hierarchical_vectors(
        store,
        external_id="exclusive-video",
        user_id="alice",
        shared_external_id=False,
    )

    assert store.calls == [
        ("exclusive-video", "alice"),
        ("exclusive-video", None),
    ]
