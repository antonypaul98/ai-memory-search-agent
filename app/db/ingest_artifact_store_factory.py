"""Backend selection for YouTube ingest artifacts.

Transcript hashes and serialized capsule JSON must follow the same backend choice
as the rest of the YouTube persistence boundary. Reusing youtube_store_backend
prevents split-brain production state.
"""

from __future__ import annotations

from app.config import Settings
from app.db.postgres_ingest_artifact_store import PostgresIngestArtifactStore
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.sqlite_ingest_artifact_store import SQLiteIngestArtifactStore


def get_ingest_artifact_store(settings: Settings):
    """Return the artifact store selected by the YouTube persistence backend."""
    if settings.youtube_store_backend == "sqlite":
        return SQLiteIngestArtifactStore(settings)
    if settings.youtube_store_backend == "postgres":
        return PostgresIngestArtifactStore(get_postgres_connection_factory(settings))
    raise ValueError(f"Unsupported YouTube store backend: {settings.youtube_store_backend}")
