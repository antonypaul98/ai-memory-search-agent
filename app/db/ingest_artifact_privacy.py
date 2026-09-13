"""Backend-aware ingest-artifact privacy deletion for P-03."""

from __future__ import annotations

from app.db.postgres_ingest_artifact_store import PostgresIngestArtifactStore
from app.db.sqlite_ingest_artifact_store import SQLiteIngestArtifactStore


def delete_capsule_artifact(
    store: SQLiteIngestArtifactStore | PostgresIngestArtifactStore,
    *,
    user_id: str,
    video_id: str,
    shared_external_id: bool,
) -> None:
    """Delete one user's capsule through the selected persistence boundary.

    Legacy SQLite capsule rows are globally keyed by ``video_id`` and therefore
    must be retained while another tenant references the same external content.
    Postgres rows are tenant-keyed, so the requesting tenant's capsule must be
    cleared even when another tenant references the same video. Unknown stores
    fail closed rather than falling back to SQLite.
    """
    if isinstance(store, SQLiteIngestArtifactStore):
        if not shared_external_id:
            store.delete_capsule_json(user_id=user_id, video_id=video_id)
        return

    if isinstance(store, PostgresIngestArtifactStore):
        store.delete_capsule_json(user_id=user_id, video_id=video_id)
        return

    raise TypeError(f"Unsupported ingest artifact store: {type(store).__name__}")
