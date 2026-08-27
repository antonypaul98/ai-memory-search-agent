"""Provider-neutral model routing with BYO credentials and free-tier awareness.

This layer deliberately does not pool community keys, create extra accounts, or bypass
upstream rate limits. It routes only across providers the operator has explicitly
configured and records local usage so free-tier budgets can be respected proactively.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.config import Settings, get_settings
from app.models.model_router import (
    ModelCatalogItem,
    ModelCatalogResponse,
    ModelRouteAttempt,
    ModelRouteMode,
    ModelRouteRequest,
    ModelRouteResponse,
    ModelTaskType,
    ModelTokenUsage,
)


class ModelRouteError(RuntimeError):
    """Raised when no permitted/configured route can complete a request."""


class ModelExecutionError(RuntimeError):
    def __init__(self, message: str, *, http_status: int | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status


@dataclass(frozen=True)
class ModelProfile:
    provider_id: str
    model_id: str
    base_url: str
    api_key_env: str = ""
    protocol: str = "openai_compatible"
    free_tier: bool = False
    capabilities: frozenset[str] = field(default_factory=lambda: frozenset({"general"}))
    quality_score: float = 0.5
    estimated_latency_ms: float = 500.0
    priority: int = 100
    daily_request_budget: int | None = None
    daily_token_budget: int | None = None

    @property
    def route_id(self) -> str:
        return f"{self.provider_id}:{self.model_id}"

    @property
    def configured(self) -> bool:
        if self.protocol == "ollama":
            return bool(self.model_id and self.base_url)
        return bool(self.model_id and self.base_url and os.environ.get(self.api_key_env, "").strip())


@dataclass(frozen=True)
class ModelExecutionResult:
    content: str
    usage: ModelTokenUsage


class ModelExecutor(Protocol):
    def complete(self, profile: ModelProfile, request: ModelRouteRequest) -> ModelExecutionResult:
        ...


class HttpModelExecutor:
    """HTTP executor for OpenAI-compatible servers and local Ollama."""

    def __init__(self, timeout_sec: int = 60) -> None:
        self._timeout_sec = timeout_sec

    def complete(self, profile: ModelProfile, request: ModelRouteRequest) -> ModelExecutionResult:
        if profile.protocol == "ollama":
            return self._ollama(profile, request)
        if profile.protocol != "openai_compatible":
            raise ModelExecutionError(f"Unsupported model protocol: {profile.protocol}")
        return self._openai_compatible(profile, request)

    def _openai_compatible(
        self, profile: ModelProfile, request: ModelRouteRequest
    ) -> ModelExecutionResult:
        api_key = os.environ.get(profile.api_key_env, "").strip()
        if not api_key:
            raise ModelExecutionError("Provider API key is not configured")
        base = profile.base_url.rstrip("/")
        url = f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"
        payload = {
            "model": profile.model_id,
            "messages": [{"role": "user", "content": request.prompt}],
            "stream": False,
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=min(self._timeout_sec, request.max_latency_ms / 1000)) as client:
                response = client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ModelExecutionError("Provider timed out") from exc
        except httpx.HTTPError as exc:
            raise ModelExecutionError("Provider transport error") from exc

        if response.status_code >= 400:
            raise ModelExecutionError(
                f"Provider returned HTTP {response.status_code}",
                http_status=response.status_code,
            )
        try:
            data = response.json()
            choices = data.get("choices") or []
            content = str(choices[0].get("message", {}).get("content") or "").strip()
            if not content:
                raise ModelExecutionError("Provider returned an empty completion")
            raw_usage = data.get("usage") or {}
            usage = ModelTokenUsage(
                prompt_tokens=max(0, int(raw_usage.get("prompt_tokens") or 0)),
                completion_tokens=max(0, int(raw_usage.get("completion_tokens") or 0)),
                total_tokens=max(0, int(raw_usage.get("total_tokens") or 0)),
            )
            return ModelExecutionResult(content=content, usage=_fill_usage(usage, request.prompt, content))
        except (ValueError, TypeError, IndexError, AttributeError) as exc:
            if isinstance(exc, ModelExecutionError):
                raise
            raise ModelExecutionError("Provider returned malformed JSON") from exc

    def _ollama(self, profile: ModelProfile, request: ModelRouteRequest) -> ModelExecutionResult:
        url = profile.base_url.rstrip("/") + "/api/chat"
        payload = {
            "model": profile.model_id,
            "messages": [{"role": "user", "content": request.prompt}],
            "stream": False,
            "options": {"temperature": request.temperature, "num_predict": request.max_output_tokens},
        }
        try:
            with httpx.Client(timeout=min(self._timeout_sec, request.max_latency_ms / 1000)) as client:
                response = client.post(url, json=payload)
            if response.status_code >= 400:
                raise ModelExecutionError(
                    f"Ollama returned HTTP {response.status_code}",
                    http_status=response.status_code,
                )
            data = response.json()
            content = str(data.get("message", {}).get("content") or data.get("response") or "").strip()
            if not content:
                raise ModelExecutionError("Ollama returned an empty completion")
            usage = ModelTokenUsage(
                prompt_tokens=max(0, int(data.get("prompt_eval_count") or 0)),
                completion_tokens=max(0, int(data.get("eval_count") or 0)),
                total_tokens=max(
                    0,
                    int(data.get("prompt_eval_count") or 0) + int(data.get("eval_count") or 0),
                ),
            )
            return ModelExecutionResult(content=content, usage=_fill_usage(usage, request.prompt, content))
        except httpx.TimeoutException as exc:
            raise ModelExecutionError("Ollama timed out") from exc
        except httpx.HTTPError as exc:
            raise ModelExecutionError("Ollama transport error") from exc
        except (ValueError, TypeError, AttributeError) as exc:
            raise ModelExecutionError("Ollama returned malformed JSON") from exc


class ModelUsageLedger:
    """Durable tenant-scoped local accounting for provider free-tier budgets."""

    def __init__(self, settings: Settings) -> None:
        self._db_path = settings.sqlite_path
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_table()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS model_route_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    route_id TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_model_route_usage_user_route_time "
                "ON model_route_usage(user_id, route_id, created_at)"
            )

    def today(self, *, user_id: str, route_id: str) -> tuple[int, int]:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS requests, COALESCE(SUM(total_tokens), 0) AS tokens
                FROM model_route_usage
                WHERE user_id = ? AND route_id = ? AND substr(created_at, 1, 10) = ?
                """,
                (user_id, route_id, day),
            ).fetchone()
        return int(row["requests"] or 0), int(row["tokens"] or 0)

    def record(self, *, user_id: str, profile: ModelProfile, usage: ModelTokenUsage) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO model_route_usage(
                    user_id, route_id, provider_id, model_id,
                    prompt_tokens, completion_tokens, total_tokens, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    profile.route_id,
                    profile.provider_id,
                    profile.model_id,
                    usage.prompt_tokens,
                    usage.completion_tokens,
                    usage.total_tokens,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )


class ModelRouter:
    """Choose the best configured model per request, with explicit pinning support."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        profiles: list[ModelProfile] | None = None,
        executor: ModelExecutor | None = None,
        ledger: ModelUsageLedger | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._profiles = profiles if profiles is not None else load_model_profiles(self._settings)
        self._executor = executor or HttpModelExecutor(self._settings.llm_timeout_sec)
        self._ledger = ledger or ModelUsageLedger(self._settings)
        self._cooldowns: dict[str, float] = {}

    def route(self, request: ModelRouteRequest, *, user_id: str) -> ModelRouteResponse:
        task_type = _resolve_task_type(request)
        resolved = request.model_copy(update={"task_type": task_type, "prompt": request.prompt.strip()})
        if not resolved.prompt:
            raise ModelRouteError("Prompt cannot be empty")

        profiles = self._candidate_profiles(resolved, user_id=user_id)
        if not profiles:
            raise ModelRouteError("No configured model route satisfies this request")

        attempts: list[ModelRouteAttempt] = []
        started = time.perf_counter()
        for index, profile in enumerate(profiles[: resolved.max_provider_calls]):
            if (time.perf_counter() - started) * 1000 >= resolved.max_latency_ms:
                break
            call_started = time.perf_counter()
            try:
                result = self._executor.complete(profile, resolved)
                latency_ms = round((time.perf_counter() - call_started) * 1000, 3)
                self._ledger.record(user_id=user_id, profile=profile, usage=result.usage)
                attempts.append(
                    ModelRouteAttempt(
                        provider_id=profile.provider_id,
                        model_id=profile.model_id,
                        route_id=profile.route_id,
                        status="ok",
                        free_tier=profile.free_tier,
                        latency_ms=latency_ms,
                        reason=_selection_reason(profile, resolved),
                    )
                )
                return ModelRouteResponse(
                    content=result.content,
                    provider_id=profile.provider_id,
                    model_id=profile.model_id,
                    route_id=profile.route_id,
                    mode=resolved.mode,
                    task_type=task_type,
                    free_tier=profile.free_tier,
                    fallback_used=index > 0,
                    attempts=attempts,
                    usage=result.usage,
                    route_fingerprint=_fingerprint(resolved, profile, attempts),
                )
            except ModelExecutionError as exc:
                latency_ms = round((time.perf_counter() - call_started) * 1000, 3)
                attempts.append(
                    ModelRouteAttempt(
                        provider_id=profile.provider_id,
                        model_id=profile.model_id,
                        route_id=profile.route_id,
                        status="error",
                        free_tier=profile.free_tier,
                        latency_ms=latency_ms,
                        reason=str(exc),
                        http_status=exc.http_status,
                    )
                )
                if exc.http_status == 429 or (exc.http_status is not None and exc.http_status >= 500):
                    self._cooldowns[profile.route_id] = time.monotonic() + self._settings.model_router_cooldown_sec
                if resolved.mode == ModelRouteMode.PINNED:
                    break

        detail = "; ".join(f"{a.route_id}: {a.reason}" for a in attempts) or "routing deadline reached"
        raise ModelRouteError(f"All permitted model routes failed ({detail})")

    def catalog(self, *, user_id: str) -> ModelCatalogResponse:
        items: list[ModelCatalogItem] = []
        for profile in sorted(self._profiles, key=lambda item: (item.provider_id, item.model_id)):
            requests_used, tokens_used = self._ledger.today(user_id=user_id, route_id=profile.route_id)
            req_remaining = (
                max(0, profile.daily_request_budget - requests_used)
                if profile.daily_request_budget is not None
                else None
            )
            token_remaining = (
                max(0, profile.daily_token_budget - tokens_used)
                if profile.daily_token_budget is not None
                else None
            )
            items.append(
                ModelCatalogItem(
                    provider_id=profile.provider_id,
                    model_id=profile.model_id,
                    route_id=profile.route_id,
                    protocol=profile.protocol,
                    configured=profile.configured,
                    free_tier=profile.free_tier,
                    capabilities=sorted(profile.capabilities),
                    quality_score=profile.quality_score,
                    estimated_latency_ms=profile.estimated_latency_ms,
                    daily_request_budget=profile.daily_request_budget,
                    daily_token_budget=profile.daily_token_budget,
                    requests_used_today=requests_used,
                    tokens_used_today=tokens_used,
                    requests_remaining_estimate=req_remaining,
                    tokens_remaining_estimate=token_remaining,
                )
            )
        return ModelCatalogResponse(models=items)

    def _candidate_profiles(self, request: ModelRouteRequest, *, user_id: str) -> list[ModelProfile]:
        now = time.monotonic()
        configured = [profile for profile in self._profiles if profile.configured]
        if request.mode == ModelRouteMode.PINNED:
            needle = (request.pinned_model or "").strip()
            matches = [
                profile
                for profile in configured
                if profile.route_id == needle or profile.model_id == needle
            ]
            if not matches:
                return []
            # Pinning means model pinning: never substitute a different model.
            matches = [profile for profile in matches if self._quota_available(profile, user_id=user_id)]
            return sorted(matches, key=lambda profile: (profile.priority, profile.provider_id))[:1]

        candidates: list[ModelProfile] = []
        task = request.task_type.value
        for profile in configured:
            if self._cooldowns.get(profile.route_id, 0.0) > now:
                continue
            if task not in profile.capabilities and "general" not in profile.capabilities:
                continue
            if not self._quota_available(profile, user_id=user_id):
                continue
            candidates.append(profile)
        return sorted(candidates, key=lambda profile: _profile_sort_key(profile, request, user_id, self._ledger))

    def _quota_available(self, profile: ModelProfile, *, user_id: str) -> bool:
        requests_used, tokens_used = self._ledger.today(user_id=user_id, route_id=profile.route_id)
        if profile.daily_request_budget is not None and requests_used >= profile.daily_request_budget:
            return False
        if profile.daily_token_budget is not None and tokens_used >= profile.daily_token_budget:
            return False
        return True


def load_model_profiles(settings: Settings) -> list[ModelProfile]:
    """Load safe provider metadata; credentials remain in environment variables only."""
    profiles: list[ModelProfile] = []

    # A stable, provider-managed free-model router is useful as the zero-config free
    # route whenever the operator has supplied their own OpenRouter key.
    profiles.append(
        ModelProfile(
            provider_id="openrouter",
            model_id="openrouter/free",
            base_url="https://openrouter.ai/api/v1",
            api_key_env="OPENROUTER_API_KEY",
            free_tier=True,
            capabilities=frozenset(
                {"general", "fast", "reasoning", "coding", "summarization", "extraction"}
            ),
            quality_score=0.72,
            estimated_latency_ms=900,
            priority=50,
        )
    )

    # Preserve the existing single-provider configuration as another router candidate.
    if settings.llm_provider == "ollama" and settings.llm_model.strip():
        profiles.append(
            ModelProfile(
                provider_id="ollama-local",
                model_id=settings.llm_model.strip(),
                base_url=settings.llm_base_url,
                protocol="ollama",
                free_tier=True,
                capabilities=frozenset(
                    {"general", "fast", "reasoning", "coding", "summarization", "extraction"}
                ),
                quality_score=0.65,
                estimated_latency_ms=350,
                priority=20,
            )
        )
    elif settings.llm_provider == "openai_compatible" and settings.llm_model.strip():
        profiles.append(
            ModelProfile(
                provider_id="configured-openai-compatible",
                model_id=settings.llm_model.strip(),
                base_url=settings.llm_base_url,
                api_key_env=settings.llm_api_key_env,
                free_tier=False,
                capabilities=frozenset(
                    {"general", "fast", "reasoning", "coding", "summarization", "extraction"}
                ),
                quality_score=0.8,
                estimated_latency_ms=500,
                priority=40,
            )
        )

    raw_catalog = settings.model_router_catalog_json.strip()
    if raw_catalog:
        try:
            items = json.loads(raw_catalog)
        except json.JSONDecodeError as exc:
            raise ModelRouteError("MODEL_ROUTER_CATALOG_JSON is not valid JSON") from exc
        if not isinstance(items, list):
            raise ModelRouteError("MODEL_ROUTER_CATALOG_JSON must be a JSON array")
        for item in items:
            if not isinstance(item, dict):
                raise ModelRouteError("Each model router catalog item must be an object")
            profiles.append(_profile_from_mapping(item))

    # Exact route IDs are the canonical identity. Last duplicate wins, which lets an
    # explicit operator catalog override conservative built-in metadata without code edits.
    unique: dict[str, ModelProfile] = {}
    for profile in profiles:
        unique[profile.route_id] = profile
    return list(unique.values())


def _profile_from_mapping(item: dict[str, Any]) -> ModelProfile:
    provider_id = str(item.get("provider_id") or "").strip()
    model_id = str(item.get("model_id") or "").strip()
    base_url = str(item.get("base_url") or "").strip()
    api_key_env = str(item.get("api_key_env") or "").strip()
    protocol = str(item.get("protocol") or "openai_compatible").strip()
    if not provider_id or not model_id or not base_url:
        raise ModelRouteError("Catalog entries require provider_id, model_id, and base_url")
    if protocol not in {"openai_compatible", "ollama"}:
        raise ModelRouteError(f"Unsupported catalog protocol: {protocol}")
    if protocol != "ollama" and not api_key_env:
        raise ModelRouteError("OpenAI-compatible catalog entries require api_key_env")
    capabilities = {
        str(value).strip().lower()
        for value in (item.get("capabilities") or ["general"])
        if str(value).strip()
    }
    return ModelProfile(
        provider_id=provider_id,
        model_id=model_id,
        base_url=base_url,
        api_key_env=api_key_env,
        protocol=protocol,
        free_tier=bool(item.get("free_tier", False)),
        capabilities=frozenset(capabilities or {"general"}),
        quality_score=_clamp(float(item.get("quality_score", 0.5))),
        estimated_latency_ms=max(1.0, float(item.get("estimated_latency_ms", 500.0))),
        priority=int(item.get("priority", 100)),
        daily_request_budget=_optional_positive_int(item.get("daily_request_budget")),
        daily_token_budget=_optional_positive_int(item.get("daily_token_budget")),
    )


def _resolve_task_type(request: ModelRouteRequest) -> ModelTaskType:
    if request.task_type != ModelTaskType.AUTO:
        return request.task_type
    prompt = request.prompt.lower()
    if any(token in prompt for token in ("code", "debug", "function", "python", "javascript", "sql", "compile", "stack trace")):
        return ModelTaskType.CODING
    if any(token in prompt for token in ("extract", "return json", "fields", "schema", "parse into")):
        return ModelTaskType.EXTRACTION
    if any(token in prompt for token in ("summarize", "summary", "tl;dr", "recap")):
        return ModelTaskType.SUMMARIZATION
    if any(token in prompt for token in ("reason", "analyze", "analyse", "why", "compare", "tradeoff", "trade-off", "prove")):
        return ModelTaskType.REASONING
    if len(prompt) <= 160 and any(token in prompt for token in ("quick", "short", "simple", "brief")):
        return ModelTaskType.FAST
    return ModelTaskType.GENERAL


def _profile_sort_key(
    profile: ModelProfile,
    request: ModelRouteRequest,
    user_id: str,
    ledger: ModelUsageLedger,
) -> tuple[Any, ...]:
    requests_used, tokens_used = ledger.today(user_id=user_id, route_id=profile.route_id)
    if profile.daily_token_budget:
        headroom = max(0.0, 1.0 - tokens_used / profile.daily_token_budget)
    elif profile.daily_request_budget:
        headroom = max(0.0, 1.0 - requests_used / profile.daily_request_budget)
    else:
        headroom = 0.5
    free_rank = 0 if request.prefer_free and profile.free_tier else (1 if request.prefer_free else 0)
    if request.task_type == ModelTaskType.FAST:
        return (free_rank, profile.estimated_latency_ms, -profile.quality_score, -headroom, profile.priority, profile.route_id)
    return (free_rank, -profile.quality_score, profile.estimated_latency_ms, -headroom, profile.priority, profile.route_id)


def _selection_reason(profile: ModelProfile, request: ModelRouteRequest) -> str:
    if request.mode == ModelRouteMode.PINNED:
        return "user_pinned_model"
    if request.prefer_free and profile.free_tier:
        return f"free_tier_{request.task_type.value}_match"
    return f"best_{request.task_type.value}_match"


def _fill_usage(usage: ModelTokenUsage, prompt: str, content: str) -> ModelTokenUsage:
    prompt_tokens = usage.prompt_tokens or _estimate_tokens(prompt)
    completion_tokens = usage.completion_tokens or _estimate_tokens(content)
    total = usage.total_tokens or prompt_tokens + completion_tokens
    return ModelTokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total,
    )


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(math.ceil(len(text.encode("utf-8")) / 4)))


def _fingerprint(
    request: ModelRouteRequest,
    profile: ModelProfile,
    attempts: list[ModelRouteAttempt],
) -> str:
    payload = {
        "prompt_sha256": hashlib.sha256(request.prompt.encode("utf-8")).hexdigest(),
        "mode": request.mode.value,
        "task_type": request.task_type.value,
        "prefer_free": request.prefer_free,
        "selected_route": profile.route_id,
        "attempts": [
            {
                "route_id": attempt.route_id,
                "status": attempt.status,
                "http_status": attempt.http_status,
            }
            for attempt in attempts
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "modelroute_" + hashlib.sha256(encoded).hexdigest()


def _optional_positive_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    parsed = int(value)
    return parsed if parsed > 0 else None


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
