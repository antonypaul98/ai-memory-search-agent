"""Context routing contract, policy, fallback, shadow, and API tests."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.api.dependencies import get_context_router
from app.models.context import ContextEvidence, ContextRequest, ContextRouteStrategy
from app.models.user import LOCAL_DEFAULT_USER_ID
from app.services.context_router import (
    ContextProviderProfile,
    ContextRouter,
    ProviderResult,
)


@dataclass
class FakeProvider:
    profile: ContextProviderProfile
    candidates: list[ContextEvidence]
    fail: bool = False
    calls: int = 0
    last_user_id: str | None = None

    def supports(self, request: ContextRequest) -> bool:
        return True

    def retrieve(self, request: ContextRequest, *, user_id: str) -> ProviderResult:
        self.calls += 1
        self.last_user_id = user_id
        if self.fail:
            raise RuntimeError("provider unavailable")
        return ProviderResult(candidates=list(self.candidates))


def _evidence(
    evidence_id: str,
    *,
    provider_id: str,
    text: str = "relevant evidence",
    relevance: float = 0.9,
    confidence: float = 0.9,
    trust: float = 0.8,
    observed_at: str | None = "2026-08-27T12:00:00+00:00",
    source_type: str = "web",
) -> ContextEvidence:
    return ContextEvidence(
        evidence_id=evidence_id,
        provider_id=provider_id,
        source_type=source_type,
        source_ref=f"https://example.com/{evidence_id}",
        title=evidence_id,
        text=text,
        relevance_score=relevance,
        confidence=confidence,
        trust_score=trust,
        observed_at=observed_at,
        token_estimate=max(1, len(text) // 4),
    )


def _provider(
    provider_id: str,
    candidates: list[ContextEvidence],
    *,
    latency: float = 100,
    cost: float = 0,
    trust: float = 0.8,
    priority: int = 100,
    fail: bool = False,
) -> FakeProvider:
    return FakeProvider(
        profile=ContextProviderProfile(
            provider_id=provider_id,
            priority=priority,
            estimated_latency_ms=latency,
            estimated_cost_per_1k_tokens=cost,
            trust_score=trust,
        ),
        candidates=candidates,
        fail=fail,
    )


class TestContextRouter:
    def test_falls_back_when_primary_errors(self) -> None:
        primary = _provider("primary", [], priority=1, fail=True)
        fallback = _provider(
            "fallback",
            [_evidence("e1", provider_id="fallback")],
            priority=2,
        )
        packet = ContextRouter([primary, fallback]).route(
            ContextRequest(task="find the answer"),
            user_id="user-a",
        )

        assert packet.receipt.live_provider_id == "fallback"
        assert packet.receipt.selected_evidence_ids == ["e1"]
        assert [attempt.status for attempt in packet.receipt.provider_attempts] == ["error", "ok"]
        assert packet.receipt.provider_attempts[1].role == "fallback"

    def test_fastest_strategy_selects_lowest_latency_provider(self) -> None:
        slow = _provider(
            "slow",
            [_evidence("slow-e", provider_id="slow")],
            latency=500,
            priority=1,
        )
        fast = _provider(
            "fast",
            [_evidence("fast-e", provider_id="fast")],
            latency=20,
            priority=99,
        )
        packet = ContextRouter([slow, fast]).route(
            ContextRequest(task="answer", strategy=ContextRouteStrategy.FASTEST),
            user_id="user-a",
        )

        assert packet.receipt.live_provider_id == "fast"
        assert fast.calls == 1
        assert slow.calls == 0

    def test_shadow_provider_never_changes_live_packet(self) -> None:
        live = _provider(
            "live",
            [_evidence("live-e", provider_id="live", relevance=0.7)],
            priority=1,
        )
        shadow = _provider(
            "shadow",
            [_evidence("shadow-e", provider_id="shadow", relevance=1.0)],
            priority=2,
        )
        packet = ContextRouter([live, shadow]).route(
            ContextRequest(task="answer", shadow=True, max_provider_calls=2),
            user_id="user-a",
        )

        assert packet.receipt.live_provider_id == "live"
        assert packet.receipt.selected_evidence_ids == ["live-e"]
        assert shadow.calls == 1
        assert packet.receipt.provider_attempts[1].role == "shadow"

    def test_strict_freshness_and_confidence_trigger_fallback(self) -> None:
        weak = _provider(
            "weak",
            [
                _evidence(
                    "old",
                    provider_id="weak",
                    confidence=0.2,
                    observed_at="2020-01-01T00:00:00+00:00",
                )
            ],
            priority=1,
        )
        trusted = _provider(
            "trusted",
            [_evidence("fresh", provider_id="trusted", confidence=0.95)],
            priority=2,
        )
        packet = ContextRouter([weak, trusted]).route(
            ContextRequest(
                task="answer",
                min_confidence=0.8,
                freshness_max_age_seconds=86400 * 7,
            ),
            user_id="user-a",
        )

        assert packet.receipt.live_provider_id == "trusted"
        assert "fresh" in packet.receipt.selected_evidence_ids
        assert any(item.evidence_id == "old" for item in packet.receipt.omissions)

    def test_token_budget_is_never_exceeded(self) -> None:
        provider = _provider(
            "p",
            [
                _evidence("e1", provider_id="p", text="alpha " * 80, relevance=0.95),
                _evidence("e2", provider_id="p", text="beta " * 80, relevance=0.90),
                _evidence("e3", provider_id="p", text="gamma " * 80, relevance=0.85),
            ],
            priority=1,
        )
        packet = ContextRouter([provider]).route(
            ContextRequest(task="answer", token_budget=128),
            user_id="user-a",
        )

        assert packet.receipt.token_estimate <= 128
        assert any(item.reason == "token_budget" for item in packet.receipt.omissions)

    def test_route_fingerprint_is_stable_for_same_decision(self) -> None:
        provider = _provider(
            "p",
            [_evidence("e1", provider_id="p", observed_at=None)],
            priority=1,
        )
        router = ContextRouter([provider])
        request = ContextRequest(task="same task")
        first = router.route(request, user_id="user-a")
        second = router.route(request, user_id="user-a")

        assert first.receipt.route_fingerprint == second.receipt.route_fingerprint


class TestContextRouteAPI:
    def test_routes_with_authenticated_tenant_scope(self, client: TestClient) -> None:
        provider = _provider(
            "api-provider",
            [_evidence("api-e", provider_id="api-provider")],
            priority=1,
        )
        router = ContextRouter([provider])

        from app.main import app

        app.dependency_overrides[get_context_router] = lambda: router
        response = client.post(
            "/api/v1/context/route",
            json={"task": "prepare useful context", "token_budget": 512},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["receipt"]["live_provider_id"] == "api-provider"
        assert body["evidence"][0]["evidence_id"] == "api-e"
        assert provider.last_user_id == LOCAL_DEFAULT_USER_ID
