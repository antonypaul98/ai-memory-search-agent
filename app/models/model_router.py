"""Typed contracts for provider-neutral model routing."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class ModelRouteMode(str, Enum):
    AUTO = "auto"
    PINNED = "pinned"


class ModelTaskType(str, Enum):
    AUTO = "auto"
    GENERAL = "general"
    FAST = "fast"
    REASONING = "reasoning"
    CODING = "coding"
    SUMMARIZATION = "summarization"
    EXTRACTION = "extraction"


class ModelRouteRequest(BaseModel):
    """One inference request and its routing constraints.

    `pinned_model` accepts either an exact route ID (`provider:model`) or an exact
    model ID. Pinned requests never fall over to a different model.
    """

    prompt: str = Field(min_length=1, max_length=200_000)
    mode: ModelRouteMode = ModelRouteMode.AUTO
    pinned_model: str | None = None
    task_type: ModelTaskType = ModelTaskType.AUTO
    prefer_free: bool = True
    max_provider_calls: int = Field(default=3, ge=1, le=10)
    max_latency_ms: int = Field(default=60_000, ge=100, le=300_000)
    max_output_tokens: int = Field(default=768, ge=1, le=16_384)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)

    @model_validator(mode="after")
    def validate_pin(self) -> "ModelRouteRequest":
        if self.mode == ModelRouteMode.PINNED and not (self.pinned_model or "").strip():
            raise ValueError("pinned_model is required when mode='pinned'")
        return self


class ModelTokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ModelRouteAttempt(BaseModel):
    provider_id: str
    model_id: str
    route_id: str
    status: str
    free_tier: bool = False
    latency_ms: float | None = None
    reason: str = ""
    http_status: int | None = None


class ModelRouteResponse(BaseModel):
    content: str
    provider_id: str
    model_id: str
    route_id: str
    mode: ModelRouteMode
    task_type: ModelTaskType
    free_tier: bool
    fallback_used: bool = False
    attempts: list[ModelRouteAttempt] = Field(default_factory=list)
    usage: ModelTokenUsage = Field(default_factory=ModelTokenUsage)
    route_fingerprint: str


class ModelCatalogItem(BaseModel):
    provider_id: str
    model_id: str
    route_id: str
    protocol: str
    configured: bool
    free_tier: bool
    capabilities: list[str] = Field(default_factory=list)
    quality_score: float = 0.5
    estimated_latency_ms: float = 500.0
    daily_request_budget: int | None = None
    daily_token_budget: int | None = None
    requests_used_today: int = 0
    tokens_used_today: int = 0
    requests_remaining_estimate: int | None = None
    tokens_remaining_estimate: int | None = None


class ModelCatalogResponse(BaseModel):
    models: list[ModelCatalogItem] = Field(default_factory=list)
