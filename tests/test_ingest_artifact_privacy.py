from unittest.mock import MagicMock

import pytest

from app.db.ingest_artifact_privacy import delete_capsule_artifact
from app.db.postgres_ingest_artifact_store import PostgresIngestArtifactStore
from app.db.sqlite_ingest_artifact_store import SQLiteIngestArtifactStore


def _sqlite_store() -> SQLiteIngestArtifactStore:
    store = object.__new__(SQLiteIngestArtifactStore)
    store.delete_capsule_json = MagicMock()
    return store


def _postgres_store() -> PostgresIngestArtifactStore:
    store = object.__new__(PostgresIngestArtifactStore)
    store.delete_capsule_json = MagicMock()
    return store


def test_sqlite_shared_capsule_is_preserved() -> None:
    store = _sqlite_store()

    delete_capsule_artifact(
        store,
        user_id="tenant-a",
        video_id="video-1",
        shared_external_id=True,
    )

    store.delete_capsule_json.assert_not_called()


def test_sqlite_unshared_capsule_is_deleted_through_selected_store() -> None:
    store = _sqlite_store()

    delete_capsule_artifact(
        store,
        user_id="tenant-a",
        video_id="video-1",
        shared_external_id=False,
    )

    store.delete_capsule_json.assert_called_once_with(
        user_id="tenant-a",
        video_id="video-1",
    )


def test_postgres_shared_video_still_deletes_requesting_tenant_capsule() -> None:
    store = _postgres_store()

    delete_capsule_artifact(
        store,
        user_id="tenant-a",
        video_id="video-1",
        shared_external_id=True,
    )

    store.delete_capsule_json.assert_called_once_with(
        user_id="tenant-a",
        video_id="video-1",
    )


def test_unknown_artifact_store_fails_closed() -> None:
    with pytest.raises(TypeError, match="Unsupported ingest artifact store"):
        delete_capsule_artifact(
            object(),
            user_id="tenant-a",
            video_id="video-1",
            shared_external_id=False,
        )
