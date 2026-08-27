"""Provider-neutral, deterministic context routing.

The first production provider is the existing AHME memory engine. The router contract is
intentionally provider-agnostic so future adapters (enterprise search, temporal memory,
local files, or third-party memory services) can compete per request without changing
callers.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from app.models.context import (
    ContextEvidence,
    ContextOmission,
    ContextPacket,
    ContextProviderAttempt,
    ContextReceipt,
    ContextRequest,
    ContextRouteStrategy,
)
from app.services.search_service import SearchService


@dataclass(frozen=True)
class ContextProviderProfile:
    """Static routing hints; lower priority values are preferred in balanced mode."""

    provider_id: str
    priority: int = 100
    estimated_latency_ms: float = 250.0
    estimated_cost_per_1k_tokens: float = 0.0
    trust_score: float = 0.5


@dataclass
class ProviderResult:
    candidates: list[ContextEvidence]


class ContextProvider(Protocol):
    """Minimal adapter contract for any context/memory backend."""

    profile: ContextProviderProfile

    def supports(self, request: ContextRequest) -> bool:
        ...

    def retrieve(self, request: ContextRequest, *, user_id: str) -> ProviderResult:
        ...


class LocalMemoryContextProvider:
    """Adapter over the project's existing tenant-scoped AHME/SearchService path."""

    profile = ContextProviderProfile(
        provider_id="local-memory-ahme",
        priority=10,
        estimated_latency_ms=120.0,
        estimated_cost_per_1k_tokens=0.0,
        trust_score=0.82,
    )

    def __init__(self, search_service: SearchService) -> None:
        self._search_service = search_service

    def supports(self, request: ContextRequest) -> bool:
        return True

    def retrieve(self, request: ContextRequest, *, user_id: str) -> ProviderResult:
        # Fetch a wider candidate frontier than the legacy UI search, then let the
        # context router perform strict SLA/policy/budget selection.
        response = self._search_service.search(
            request.task,
            limit=20,
            user_id=user_id,
        )
        candidates: list[ContextEvidence] = []
        for item in response.results:
            text = (item.matched_text or item.ai_summary or item.one_line_memory or "").strip()
            if not text:
                continue
            source_ref = item.citation_ref or item.timestamp_url or item.original_url
            evidence_seed = f"{item.source_type}|{source_ref}|{text}"
            evidence_id = "ctx_" + hashlib.sha256(evidence_seed.encode("utf-8")).hexdigest()[:20]
            candidates.append(
                ContextEvidence(
                    evidence_id=evidence_id,
                    provider_id=self.profile.provider_id,
                    source_type=item.source_type or "memory",
                    source_ref=source_ref,
                    title=item.title,
                    text=text,
                    relevance_score=_clamp01(item.relevance_score),
                    confidence=_clamp01(
                        item.confidence if item.confidence is not None else item.relevance_score
                    ),
                    trust_score=self.profile.trust_score,
                    observed_at=item.import_date or item.published_at,
                    token_estimate=_estimate_tokens(text),
                    metadata={
                        "connector_id": item.connector_id,
                        "why_matched": item.why_matched,
                        "timestamp_url": item.timestamp_url,
                    },
                )
            )
        return ProviderResult(candidates=candidates)


class ContextRouter:
    """Select one live context path, fail over safely, and emit an auditable receipt.

    Normal requests use one provider whenever possible for low latency and predictable
    cost. A fallback is called only when the preferred provider fails or has no evidence
    that satisfies the request. Shadow mode can evaluate alternates without allowing
    shadow evidence to affect the live packet.
    """

    def __init__(self, providers: list[ContextProvider]) -> None:
        if not providers:
            raise ValueError("ContextRouter requires at least one provider")
        provider_ids = [p.profile.provider_id for p in providers]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("Context provider IDs must be unique")
        self._providers = list(providers)

    def route(self, request: ContextRequest, *, user_id: str) -> ContextPacket:
        task = request.task.strip()
        if not task:
            raise ValueError("Context task cannot be empty")
        request = request.model_copy(update={"task": task})

        providers = [p for p in self._provider_order(request) if p.supports(request)]
        attempts: list[ContextProviderAttempt] = []
        omissions: list[ContextOmission] = []
        warnings: list[str] = []
        live_provider_id: str | None = None
        live_candidates: list[ContextEvidence] = []
        started = time.perf_counter()
        calls = 0

        for provider in providers:
            if calls >= request.max_provider_calls:
                break
            elapsed_ms = (time.perf_counter() - started) * 1000
            if elapsed_ms >= request.max_latency_ms:
                attempts.append(
                    ContextProviderAttempt(
                        provider_id=provider.profile.provider_id,
                        role="fallback" if live_provider_id is None else "shadow",
                        status="deadline",
                    )
                )
                break

            role = "primary" if calls == 0 else ("shadow" if live_provider_id else "fallback")
            # Once a live provider succeeds, alternates are called only in explicit
            # shadow mode. Their output is measured but never mixed into production output.
            if live_provider_id is not None and not request.shadow:
                break

            call_started = time.perf_counter()
            calls += 1
            try:
                result = provider.retrieve(request, user_id=user_id)
                latency_ms = round((time.perf_counter() - call_started) * 1000, 3)
                accepted, rejected = _apply_request_constraints(
                    result.candidates,
                    request=request,
                )

                if live_provider_id is not None:
                    attempts.append(
                        ContextProviderAttempt(
                            provider_id=provider.profile.provider_id,
                            role="shadow",
                            status="ok" if accepted else "empty",
                            latency_ms=latency_ms,
                            candidate_count=len(accepted),
                        )
                    )
                    continue

                omissions.extend(rejected)
                if accepted:
                    live_provider_id = provider.profile.provider_id
                    live_candidates = accepted
                    attempts.append(
                        ContextProviderAttempt(
                            provider_id=provider.profile.provider_id,
                            role=role,
                            status="ok",
                            latency_ms=latency_ms,
                            candidate_count=len(accepted),
                        )
                    )
                else:
                    attempts.append(
                        ContextProviderAttempt(
                            provider_id=provider.profile.provider_id,
                            role=role,
                            status="empty",
                            latency_ms=latency_ms,
                            candidate_count=0,
                        )
                    )
            except Exception as exc:  # adapters are an isolation boundary
                attempts.append(
                    ContextProviderAttempt(
                        provider_id=provider.profile.provider_id,
                        role=role,
                        status="error",
                        latency_ms=round((time.perf_counter() - call_started) * 1000, 3),
                        error_type=type(exc).__name__,
                    )
                )

        if live_provider_id is None:
            warnings.append("No provider returned evidence satisfying the request constraints.")

        deduped, duplicate_omissions = _deduplicate(live_candidates)
        omissions.extend(duplicate_omissions)
        ranked = sorted(
            deduped,
            key=lambda evidence: (
                -_route_score(evidence),
                evidence.token_estimate,
                evidence.evidence_id,
            ),
        )

        selected: list[ContextEvidence] = []
        context_text = ""
        for evidence in ranked:
            proposed = selected + [evidence]
            rendered = _render_context(proposed)
            if _estimate_tokens(rendered) <= request.token_budget:
                selected.append(evidence)
                context_text = rendered
            else:
                omissions.append(
                    ContextOmission(
                        evidence_id=evidence.evidence_id,
                        provider_id=evidence.provider_id,
                        reason="token_budget",
                    )
                )

        token_estimate = _estimate_tokens(context_text) if context_text else 0
        if live_candidates and not selected:
            warnings.append("Eligible evidence existed but none fit inside the token budget.")

        fingerprint = _route_fingerprint(
            request=request,
            live_provider_id=live_provider_id,
            attempts=attempts,
            selected=selected,
            omissions=omissions,
        )
        receipt = ContextReceipt(
            strategy=request.strategy,
            live_provider_id=live_provider_id,
            provider_attempts=attempts,
            selected_evidence_ids=[item.evidence_id for item in selected],
            omissions=omissions,
            token_budget=request.token_budget,
            token_estimate=token_estimate,
            warnings=warnings,
            route_fingerprint=fingerprint,
        )
        return ContextPacket(
            task=request.task,
            context_text=context_text,
            evidence=selected,
            receipt=receipt,
        )

    def _provider_order(self, request: ContextRequest) -> list[ContextProvider]:
        if request.strategy == ContextRouteStrategy.FASTEST:
            return sorted(
                self._providers,
                key=lambda p: (p.profile.estimated_latency_ms, p.profile.priority, p.profile.provider_id),
            )
        if request.strategy == ContextRouteStrategy.HIGHEST_TRUST:
            return sorted(
                self._providers,
                key=lambda p: (-p.profile.trust_score, p.profile.estimated_latency_ms, p.profile.provider_id),
            )
        if request.strategy == ContextRouteStrategy.LOWEST_COST:
            return sorted(
                self._providers,
                key=lambda p: (
                    p.profile.estimated_cost_per_1k_tokens,
                    p.profile.estimated_latency_ms,
                    p.profile.provider_id,
                ),
            )
        return sorted(
            self._providers,
            key=lambda p: (p.profile.priority, p.profile.estimated_latency_ms, p.profile.provider_id),
        )


def _apply_request_constraints(
    candidates: list[ContextEvidence],
    *,
    request: ContextRequest,
) -> tuple[list[ContextEvidence], list[ContextOmission]]:
    accepted: list[ContextEvidence] = []
    omitted: list[ContextOmission] = []
    allowed_types = {item.strip().lower() for item in request.allowed_source_types if item.strip()}
    now = datetime.now(timezone.utc)

    for evidence in candidates:
        reason: str | None = None
        if allowed_types and evidence.source_type.lower() not in allowed_types:
            reason = "source_type_policy"
        elif evidence.confidence < request.min_confidence:
            reason = "confidence_below_minimum"
        elif evidence.valid_to:
            valid_to = _parse_timestamp(evidence.valid_to)
            if valid_to is not None and valid_to <= now:
                reason = "superseded_or_expired"
        if reason is None and request.freshness_max_age_seconds is not None:
            observed_at = _parse_timestamp(evidence.observed_at)
            if observed_at is None:
                reason = "freshness_unknown"
            elif (now - observed_at).total_seconds() > request.freshness_max_age_seconds:
                reason = "stale"

        if reason:
            omitted.append(
                ContextOmission(
                    evidence_id=evidence.evidence_id,
                    provider_id=evidence.provider_id,
                    reason=reason,
                )
            )
        else:
            accepted.append(evidence)
    return accepted, omitted


def _deduplicate(
    candidates: list[ContextEvidence],
) -> tuple[list[ContextEvidence], list[ContextOmission]]:
    seen: set[str] = set()
    kept: list[ContextEvidence] = []
    omitted: list[ContextOmission] = []
    for evidence in candidates:
        normalized = " ".join(evidence.text.lower().split())
        key = hashlib.sha256(f"{evidence.source_ref}|{normalized}".encode("utf-8")).hexdigest()
        if key in seen:
            omitted.append(
                ContextOmission(
                    evidence_id=evidence.evidence_id,
                    provider_id=evidence.provider_id,
                    reason="duplicate",
                )
            )
            continue
        seen.add(key)
        kept.append(evidence)
    return kept, omitted


def _route_score(evidence: ContextEvidence) -> float:
    freshness = _freshness_score(evidence.observed_at)
    return round(
        0.55 * evidence.relevance_score
        + 0.20 * evidence.confidence
        + 0.15 * evidence.trust_score
        + 0.10 * freshness,
        8,
    )


def _freshness_score(value: str | None) -> float:
    observed = _parse_timestamp(value)
    if observed is None:
        return 0.5
    age_days = max(0.0, (datetime.now(timezone.utc) - observed).total_seconds() / 86400)
    if age_days <= 7:
        return 1.0
    if age_days <= 30:
        return 0.85
    if age_days <= 180:
        return 0.7
    if age_days <= 365:
        return 0.55
    return 0.4


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = datetime.strptime(normalized[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _render_context(evidence: list[ContextEvidence]) -> str:
    blocks: list[str] = []
    for index, item in enumerate(evidence, start=1):
        title = item.title.strip() or item.source_type
        blocks.append(
            f"[C{index}] {title}\n"
            f"Source: {item.source_ref}\n"
            f"Evidence: {item.text.strip()}"
        )
    return "\n\n".join(blocks)


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    # Fast, deterministic provider-neutral estimate. Exact provider token accounting can
    # be attached by a provider adapter later without making routing depend on an LLM.
    return max(1, int(math.ceil(len(text.encode("utf-8")) / 4)))


def _route_fingerprint(
    *,
    request: ContextRequest,
    live_provider_id: str | None,
    attempts: list[ContextProviderAttempt],
    selected: list[ContextEvidence],
    omissions: list[ContextOmission],
) -> str:
    stable_attempts = [
        {
            "provider_id": attempt.provider_id,
            "role": attempt.role,
            "status": attempt.status,
            "candidate_count": attempt.candidate_count,
            "error_type": attempt.error_type,
        }
        for attempt in attempts
    ]
    payload = {
        "request": request.model_dump(mode="json"),
        "live_provider_id": live_provider_id,
        "attempts": stable_attempts,
        "selected": [item.evidence_id for item in selected],
        "omissions": [item.model_dump(mode="json") for item in omissions],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "route_" + hashlib.sha256(encoded).hexdigest()


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))
