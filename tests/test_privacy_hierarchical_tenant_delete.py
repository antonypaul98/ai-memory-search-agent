import pytest

from app.services.privacy_service import _delete_hierarchical_vectors


class _Store:
    def __init__(self, *, fail_scoped=False):
        self.calls = []
        self.fail_scoped = fail_scoped

    def delete_video(self, video_id, *, user_id=None):
        self.calls.append((video_id, user_id))
        if self.fail_scoped and user_id is not None:
            raise RuntimeError("hierarchical delete failure")


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


def test_scoped_delete_failure_propagates_before_legacy_purge():
    store = _Store(fail_scoped=True)

    with pytest.raises(RuntimeError, match="hierarchical delete failure"):
        _delete_hierarchical_vectors(
            store,
            external_id="exclusive-video",
            user_id="alice",
            shared_external_id=False,
        )

    assert store.calls == [("exclusive-video", "alice")]
