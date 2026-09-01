from __future__ import annotations

import pytest

from app.config import Settings
from app.db.ingest_artifact_store_factory import get_ingest_artifact_store
from app.db.postgres_runtime import PostgresConfigurationError
from app.db.sqlite_ingest_artifact_store import SQLiteIngestArtifactStore


def test_artifact_store_follows_default_youtube_sqlite_backend(tmp_path):
    settings = Settings(sqlite_path=str(tmp_path / "videos.db"))

    store = get_ingest_artifact_store(settings)

    assert isinstance(store, SQLiteIngestArtifactStore)


def test_artifact_store_postgres_selection_fails_closed_without_dsn(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = Settings(youtube_store_backend="postgres")

    with pytest.raises(PostgresConfigurationError):
        get_ingest_artifact_store(settings)


def test_artifact_store_reuses_youtube_backend_without_independent_switch(tmp_path):
    settings = Settings(sqlite_path=str(tmp_path / "videos.db"), youtube_store_backend="sqlite")

    assert not hasattr(settings, "ingest_artifact_store_backend")
    assert isinstance(get_ingest_artifact_store(settings), SQLiteIngestArtifactStore)
