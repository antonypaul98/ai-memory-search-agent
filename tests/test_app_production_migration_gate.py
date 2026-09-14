"""Regression coverage for the app lifespan legacy SQLite migration gate."""

import asyncio
from unittest.mock import MagicMock

import pytest

from app.config import Settings
import app.main as main_module


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
        jobs_enabled=False,
        **values,
    )


def _run_lifespan(monkeypatch, settings: Settings, migrate: MagicMock) -> None:
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "validate_runtime_topology", MagicMock())
    monkeypatch.setattr(main_module, "migrate", migrate)
    monkeypatch.setattr(main_module, "should_start_job_worker", lambda _: False)
    monkeypatch.setattr(main_module, "stop_job_worker", MagicMock())

    async def _run() -> None:
        async with main_module.lifespan(main_module.app):
            pass

    asyncio.run(_run())


def test_complete_postgres_profile_skips_app_sqlite_migration(tmp_path, monkeypatch) -> None:
    migrate = MagicMock()
    _run_lifespan(monkeypatch, _settings(tmp_path), migrate)
    migrate.assert_not_called()


def test_mixed_profile_keeps_app_sqlite_migration(tmp_path, monkeypatch) -> None:
    migrate = MagicMock()
    settings = _settings(tmp_path, fts_store_backend="sqlite")
    _run_lifespan(monkeypatch, settings, migrate)
    migrate.assert_called_once_with(settings)


@pytest.mark.parametrize("failure_at_start", [False, True])
def test_lifespan_always_stops_workers_on_failure(tmp_path, monkeypatch, failure_at_start):
    settings = _settings(tmp_path)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "should_start_job_worker", lambda _: True)
    start = MagicMock(side_effect=RuntimeError("startup failure") if failure_at_start else None)
    stop = MagicMock()
    monkeypatch.setattr(main_module, "start_job_worker", start)
    monkeypatch.setattr(main_module, "stop_job_worker", stop)

    async def run():
        async with main_module.lifespan(main_module.app):
            raise RuntimeError("lifespan failure")

    with pytest.raises(RuntimeError, match="failure"):
        asyncio.run(run())
    start.assert_called_once_with(settings)
    stop.assert_called_once()
