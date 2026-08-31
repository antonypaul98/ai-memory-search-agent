from __future__ import annotations

import pytest

from app.config import Settings
from app.db import postgres_runtime, postgres_video_registry, video_registry
from app.db.postgres_runtime import PostgresConfigurationError
from app.db.video_registry import VideoRegistry, get_video_registry, reset_video_registry_cache


@pytest.fixture(autouse=True)
def _reset_registry_cache():
    reset_video_registry_cache()
    yield
    reset_video_registry_cache()


def test_video_registry_defaults_to_sqlite(tmp_path):
    settings = Settings(sqlite_path=str(tmp_path / "videos.db"))

    registry = get_video_registry(settings)

    assert isinstance(registry, VideoRegistry)
    assert settings.memory_store_backend == "sqlite"


def test_postgres_video_registry_fails_closed_without_dsn(monkeypatch):
    env_name = "P03_VIDEO_REGISTRY_TEST_DSN"
    monkeypatch.delenv(env_name, raising=False)
    settings = Settings(memory_store_backend="postgres", postgres_dsn_env=env_name)

    with pytest.raises(PostgresConfigurationError):
        get_video_registry(settings)


def test_postgres_selection_initializes_schema_and_reuses_registry(monkeypatch):
    calls: list[object] = []
    connection_factory = object()

    class FakePostgresVideoRegistry:
        def __init__(self, settings, resolved_factory):
            calls.append(("registry", settings.memory_store_backend, resolved_factory))

    monkeypatch.setattr(
        postgres_runtime,
        "get_postgres_connection_factory",
        lambda settings: connection_factory,
    )
    monkeypatch.setattr(
        postgres_video_registry,
        "ensure_postgres_video_registry_schema",
        lambda resolved_factory: calls.append(("schema", resolved_factory)),
    )
    monkeypatch.setattr(
        postgres_video_registry,
        "PostgresVideoRegistry",
        FakePostgresVideoRegistry,
    )
    settings = Settings(memory_store_backend="postgres")

    first = get_video_registry(settings)
    second = get_video_registry(settings)

    assert first is second
    assert calls == [
        ("schema", connection_factory),
        ("registry", "postgres", connection_factory),
    ]


def test_registry_cache_key_never_contains_dsn_secret(monkeypatch):
    monkeypatch.setenv("P03_VIDEO_SECRET_DSN", "postgresql://user:secret-value@example/db")
    monkeypatch.setattr(postgres_runtime, "get_postgres_connection_factory", lambda settings: object())
    monkeypatch.setattr(postgres_video_registry, "ensure_postgres_video_registry_schema", lambda factory: None)
    monkeypatch.setattr(postgres_video_registry, "PostgresVideoRegistry", lambda settings, factory: object())

    get_video_registry(
        Settings(memory_store_backend="postgres", postgres_dsn_env="P03_VIDEO_SECRET_DSN")
    )

    keys = " ".join(video_registry._REGISTRY)
    assert "secret-value" not in keys
    assert "postgresql://" not in keys


def test_postgres_schema_keeps_tenant_composite_keys():
    statements: list[str] = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            statements.append(" ".join(str(statement).split()))
            return self

    postgres_video_registry.ensure_postgres_video_registry_schema(lambda: FakeConnection())

    ddl = " ".join(statements)
    assert "PRIMARY KEY (user_id, video_id)" in ddl
    assert "video_registry" in ddl
    assert "video_reflection" in ddl
