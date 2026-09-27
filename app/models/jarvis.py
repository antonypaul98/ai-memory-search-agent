"""Jarvis V1 core runtime request/response contracts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models.agent import AgentCommandContext, AgentCommandPlan


class JarvisRequest(BaseModel):
    """One natural-language turn through the Jarvis orchestration boundary."""

    text: str = Field(min_length=1, max_length=2000)
    context: AgentCommandContext | None = None
    limit: int = Field(default=5, ge=1, le=20)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Jarvis request cannot be empty.")
        return cleaned


class JarvisResponse(BaseModel):
    """Deterministic J01 response: plan plus bounded execution outcome."""

    plan: AgentCommandPlan
    executed: bool = False
    status: str
    message: str = ""
    result: dict[str, Any] | None = None
