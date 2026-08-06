"""Agent status and health models for the Chrome extension."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class AgentLatestMemory(BaseModel):
    memory_id: str | None = None
    title: str = ""
    source_type: str = ""
    url: str = ""
    updated_at: str | None = None


class AgentSearchEvent(BaseModel):
    query: str
    created_at: str


class AgentStatusResponse(BaseModel):
    """Aggregated agent health + memory stats for the extension popup."""

    backend_status: str = Field(description="ok | degraded | error")
    connected: bool = True
    app_name: str
    version: str = "1.1.0"
    chroma_connected: bool = False
    document_count: int = 0
    auth_enabled: bool = False
    user_id: str
    display_name: str = ""
    pending_captures: int = 0
    pending_jobs: int = 0
    today_saves: int = 0
    processing_count: int = 0
    indexed_count: int = 0
    memory_count: int = 0
    latest_memory: AgentLatestMemory | None = None
    recent_searches: list[AgentSearchEvent] = Field(default_factory=list)
    last_sync_at: str | None = None
    pwa_url: str = "http://localhost:8000/"


class AgentCommandContext(BaseModel):
    """Optional page context from the extension observer."""

    url: str | None = Field(default=None, max_length=2000)
    title: str | None = Field(default=None, max_length=500)
    platform: str | None = Field(default=None, max_length=64)


class AgentCommandStep(BaseModel):
    id: str
    label: str


class AgentCommandRequest(BaseModel):
    """Classify (and optionally execute) a natural-language agent command."""

    text: str = Field(min_length=1, max_length=2000)
    context: AgentCommandContext | None = None
    execute: bool = Field(
        default=False,
        description="When true, run safe intents (search/ask/help) immediately.",
    )
    confirm_token: str | None = Field(
        default=None,
        description="Required to proceed past the gate for bulk intents.",
    )
    limit: int = Field(default=5, ge=1, le=20)

    @field_validator("text")
    @classmethod
    def strip_text(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Command text cannot be empty.")
        return cleaned


class AgentCommandPlan(BaseModel):
    intent: str
    query: str = ""
    confidence: float = 0.0
    summary: str = ""
    requires_confirm: bool = False
    bulk: bool = False
    confirm_token: str | None = None
    workspace_url: str = ""
    steps: list[AgentCommandStep] = Field(default_factory=list)
    help_text: str | None = None
    original_text: str = ""


class AgentCommandExecuteRequest(BaseModel):
    """Execute a previously planned command."""

    intent: str = Field(min_length=1, max_length=64)
    query: str = Field(default="", max_length=2000)
    original_text: str = Field(default="", max_length=2000)
    confirm_token: str | None = Field(default=None, max_length=512)
    context: AgentCommandContext | None = None
    limit: int = Field(default=5, ge=1, le=20)

    @field_validator("intent")
    @classmethod
    def strip_intent(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("intent cannot be empty.")
        return cleaned

    @field_validator("confirm_token")
    @classmethod
    def strip_confirm_token(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned or None


class AgentCommandResponse(BaseModel):
    plan: AgentCommandPlan
    executed: bool = False
    status: str = "planned"
    message: str = ""
    result: dict[str, Any] | None = None
