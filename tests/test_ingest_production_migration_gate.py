"""Regression coverage for the ingest-service legacy SQLite migration gate."""

from unittest.mock import MagicMock

from app.config import Settings
import app.services.ingest_service as ingest_module


_POSTGRES_BACKENDS = {
    "auth_store_backend": "postgres",
    "memory_store_backend": "postgres",
    "capture_store_backend": "postgres",
    "bookmark_store_backend": "postgres",
    "fts_store_backend": "postgres",
    "semantic_cache_store_backend": "postgres",
    "youtube_store_backend": "postgres",
    "job_store_backend": "postgres",
}


def _settings(tmp_path, **overrides) -> Settings:
    values = dict(_POSTGRES_BACKENDS)
    values.update(overrides)
    return Settings(
        sqlite_path=str(tmp_path / "legacy.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        postgres_dsn_env="MEMORY_AGENT_TEST_POSTGRES_DSN",
        hierarchical_retrieval_enabled=False,
        semantic_cache_enabled=False,
        jobs_enabled=False,
        **values,
    )


def _stub_constructor_dependencies(monkeypatch) -> None:
    for name in (
        "MetadataService",
        "TranscriptService",
        "MemoryRepository",
        "get_video_registry",
        "HierarchicalStore",
        "get_fts_index",
        "UniversalMemoryService",
        "get_youtube_memory_store",
        "get_ingest_artifact_store",
        "YouTubeDuplicateDetector",
    ):
        monkeypatch.setattr(ingest_module, name, MagicMock(return_value=MagicMock()))


def test_complete_postgres_profile_skips_legacy_sqlite_migration(tmp_path, monkeypatch) -> None:
    _stub_constructor_dependencies(monkeypatch)
    migrate = MagicMock()
    monkeypatch.setattr(ingest_module, "migrate", migrate)

    ingest_module.IngestService(settings=_settings(tmp_path))

    migrate.assert_not_called()


def test_mixed_profile_keeps_legacy_sqlite_migration(tmp_path, monkeypatch) -> None:
    _stub_constructor_dependencies(monkeypatch)
    migrate = MagicMock()
    monkeypatch.setattr(ingest_module, "migrate", migrate)

    settings = _settings(tmp_path, fts_store_backend="sqlite")
    ingest_module.IngestService(settings=settings)

    migrate.assert_called_once_with(settings)
