"""Regression tests for provider-neutral model routing."""

from __future__ import annotations

from collections import defaultdict

import pytest

from app.config import Settings
from app.models.model_router import (
    ModelRouteMode,
    ModelRouteRequest,
    ModelTaskType,
    ModelTokenUsage,
)
from app.services.model_router import (
    ModelExecutionError,
    ModelExecutionResult,
    ModelProfile,
    ModelRouteError,
    ModelRouter,
    ModelUsageLedger,
)


class FakeExecutor:
    def __init__(self, outcomes: dict[str, list[object]] | None = None) -> None:
        self.outcomes = {key: list(value) for key, value in (outcomes or {}).items()}
        self.calls: list[str] = []

    def complete(self, profile: ModelProfile, request: ModelRouteRequest) -> ModelExecutionResult:
        self.calls.append(profile.route_id)
        queue = self.outcomes.get(profile.route_id, [])
        if queue:
            outcome = queue.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            if isinstance(outcome, ModelExecutionResult):
                return outcome
        return ModelExecutionResult(
            content=f"reply from {profile.route_id}",
            usage=ModelTokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )


def _profile(
    provider: str,
    model: str,
    *,
    free: bool,
    capabilities: set[str] | None = None,
    quality: float = 0.7,
    latency: float = 200,
    priority: int = 100,
    request_budget: int | None = None,
) -> ModelProfile:
    # Ollama protocol keeps the profile configured without requiring a real API key;
    # tests inject FakeExecutor so no network call occurs.
    return ModelProfile(
        provider_id=provider,
        model_id=model,
        base_url="http://test.invalid",
        protocol="ollama",
        free_tier=free,
        capabilities=frozenset(capabilities or {"general"}),
        quality_score=quality,
        estimated_latency_ms=latency,
        priority=priority,
        daily_request_budget=request_budget,
    )


def _router(
    settings: Settings,
    profiles: list[ModelProfile],
    executor: FakeExecutor,
) -> ModelRouter:
    return ModelRouter(
        settings,
        profiles=profiles,
        executor=executor,
        ledger=ModelUsageLedger(settings),
    )


def test_auto_prefers_free_capacity(test_settings: Settings) -> None:
    free = _profile("free", "fast-model", free=True, quality=0.65, latency=150)
    paid = _profile("paid", "premium-model", free=False, quality=0.98, latency=80)
    executor = FakeExecutor()
    router = _router(test_settings, [paid, free], executor)

    result = router.route(ModelRouteRequest(prompt="hello"), user_id="u1")

    assert result.route_id == free.route_id
    assert result.free_tier is True
    assert executor.calls == [free.route_id]


def test_fast_task_prefers_lower_latency_within_same_tier(test_settings: Settings) -> None:
    slow = _profile(
        "p1",
        "slow",
        free=True,
        capabilities={"fast", "general"},
        quality=0.95,
        latency=600,
    )
    fast = _profile(
        "p2",
        "fast",
        free=True,
        capabilities={"fast", "general"},
        quality=0.75,
        latency=80,
    )
    executor = FakeExecutor()
    router = _router(test_settings, [slow, fast], executor)

    result = router.route(
        ModelRouteRequest(prompt="Give me a quick short answer", task_type=ModelTaskType.FAST),
        user_id="u1",
    )

    assert result.route_id == fast.route_id


def test_rate_limit_falls_over_to_next_model(test_settings: Settings) -> None:
    first = _profile("a", "one", free=True, quality=0.9)
    second = _profile("b", "two", free=True, quality=0.8)
    executor = FakeExecutor(
        {
            first.route_id: [ModelExecutionError("rate limited", http_status=429)],
            second.route_id: [
                ModelExecutionResult(
                    content="fallback worked",
                    usage=ModelTokenUsage(prompt_tokens=4, completion_tokens=3, total_tokens=7),
                )
            ],
        }
    )
    router = _router(test_settings, [first, second], executor)

    result = router.route(ModelRouteRequest(prompt="answer this"), user_id="u1")

    assert result.content == "fallback worked"
    assert result.fallback_used is True
    assert [attempt.status for attempt in result.attempts] == ["error", "ok"]
    assert executor.calls == [first.route_id, second.route_id]


def test_pinned_model_never_substitutes_another_model(test_settings: Settings) -> None:
    pinned = _profile("a", "wanted", free=True)
    alternate = _profile("b", "other", free=True)
    executor = FakeExecutor(
        {pinned.route_id: [ModelExecutionError("down", http_status=503)]}
    )
    router = _router(test_settings, [pinned, alternate], executor)

    with pytest.raises(ModelRouteError):
        router.route(
            ModelRouteRequest(
                prompt="use exactly this model",
                mode=ModelRouteMode.PINNED,
                pinned_model=pinned.route_id,
            ),
            user_id="u1",
        )

    assert executor.calls == [pinned.route_id]


def test_daily_budget_moves_auto_routing_to_remaining_capacity(test_settings: Settings) -> None:
    free = _profile("free", "quota-one", free=True, quality=0.9, request_budget=1)
    paid = _profile("paid", "backup", free=False, quality=0.8)
    executor = FakeExecutor()
    router = _router(test_settings, [free, paid], executor)

    first = router.route(ModelRouteRequest(prompt="first"), user_id="u1")
    second = router.route(ModelRouteRequest(prompt="second"), user_id="u1")

    assert first.route_id == free.route_id
    assert second.route_id == paid.route_id


def test_usage_ledger_is_tenant_scoped(test_settings: Settings) -> None:
    profile = _profile("free", "shared", free=True)
    executor = FakeExecutor()
    router = _router(test_settings, [profile], executor)

    router.route(ModelRouteRequest(prompt="hello"), user_id="tenant-a")

    a = router.catalog(user_id="tenant-a").models[0]
    b = router.catalog(user_id="tenant-b").models[0]
    assert a.requests_used_today == 1
    assert a.tokens_used_today == 15
    assert b.requests_used_today == 0
    assert b.tokens_used_today == 0


def test_auto_task_classifier_detects_coding(test_settings: Settings) -> None:
    coding = _profile(
        "coder",
        "code-model",
        free=True,
        capabilities={"coding"},
        quality=0.9,
    )
    general = _profile("general", "chat-model", free=True, capabilities={"general"}, quality=0.5)
    executor = FakeExecutor()
    router = _router(test_settings, [general, coding], executor)

    result = router.route(
        ModelRouteRequest(prompt="Debug this Python function and explain the stack trace"),
        user_id="u1",
    )

    assert result.task_type == ModelTaskType.CODING
    assert result.route_id == coding.route_id


def test_model_route_api_supports_pin(client, test_settings: Settings) -> None:
    from app.api.dependencies import get_model_router
    from app.main import app

    profile = _profile("api", "only-model", free=True)
    executor = FakeExecutor()
    router = _router(test_settings, [profile], executor)
    app.dependency_overrides[get_model_router] = lambda: router

    response = client.post(
        "/api/v1/models/route",
        json={
            "prompt": "hello",
            "mode": "pinned",
            "pinned_model": profile.route_id,
        },
    )

    assert response.status_code == 200
    assert response.json()["route_id"] == profile.route_id
    assert response.json()["mode"] == "pinned"
