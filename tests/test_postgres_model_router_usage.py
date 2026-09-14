"""Real-Postgres acceptance for ModelRouter usage/quota accounting."""
from __future__ import annotations

import os
import sqlite3
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.models.model_router import ModelRouteRequest, ModelTokenUsage
from app.services.model_router import (
    ModelExecutionResult,
    ModelProfile,
    ModelRouter,
)


class FakeExecutor:
    def complete(self, profile: ModelProfile, request: ModelRouteRequest) -> ModelExecutionResult:
        return ModelExecutionResult(
            content="ok",
            usage=ModelTokenUsage(prompt_tokens=4, completion_tokens=3, total_tokens=7),
        )


def _profile(*, request_budget: int | None = None) -> ModelProfile:
    return ModelProfile(
        provider_id="local-test",
        model_id="quota-model",
        base_url="http://test.invalid",
        protocol="ollama",
        free_tier=True,
        capabilities=frozenset({"general"}),
        daily_request_budget=request_budget,
    )


@pytest.fixture
def pg_router_settings(monkeypatch, tmp_path):
    if not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"):
        pytest.skip("real Postgres DSN required")
    settings = Settings(
        _env_file=None,
        **{field: "postgres" for field in RELATIONAL_STORE_BACKEND_FIELDS},
        postgres_dsn_env="MEMORY_AGENT_TEST_POSTGRES_DSN",
        sqlite_path=str(tmp_path / "forbidden.db"),
        jobs_enabled=False,
    )
    attempts: list[bool] = []

    def reject(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("production ModelRouter opened relational SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject)
    nonce = uuid4().hex
    owner = f"router-owner-{nonce}"
    other = f"router-other-{nonce}"
    try:
        yield settings, owner, other
    finally:
        factory = get_postgres_connection_factory(settings)
        with factory() as conn:
            conn.execute(
                "DELETE FROM model_route_usage WHERE user_id IN (%s, %s)",
                (owner, other),
            )
        assert attempts == []
        assert not (tmp_path / "forbidden.db").exists()


def test_model_router_usage_survives_restart_and_is_tenant_scoped(pg_router_settings):
    settings, owner, other = pg_router_settings
    profile = _profile()

    first = ModelRouter(settings, profiles=[profile], executor=FakeExecutor())
    first.route(ModelRouteRequest(prompt="first"), user_id=owner)

    restarted = ModelRouter(settings, profiles=[profile], executor=FakeExecutor())
    owner_model = restarted.catalog(user_id=owner).models[0]
    other_model = restarted.catalog(user_id=other).models[0]

    assert owner_model.requests_used_today == 1
    assert owner_model.tokens_used_today == 7
    assert other_model.requests_used_today == 0
    assert other_model.tokens_used_today == 0


def test_model_router_quota_is_enforced_from_postgres_after_restart(pg_router_settings):
    settings, owner, _ = pg_router_settings
    profile = _profile(request_budget=1)

    first = ModelRouter(settings, profiles=[profile], executor=FakeExecutor())
    first.route(ModelRouteRequest(prompt="first"), user_id=owner)

    restarted = ModelRouter(settings, profiles=[profile], executor=FakeExecutor())
    with pytest.raises(Exception, match="No configured model route"):
        restarted.route(ModelRouteRequest(prompt="second"), user_id=owner)
