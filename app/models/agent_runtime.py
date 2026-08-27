"""Typed models for the Phase 4 agent runtime."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AgentPolicyTier(str, Enum):
    READ_ONLY = "read_only"
    WRITE_MEMORY = "write_memory"
    EXTERNAL = "external"
    ADMIN = "admin"


class AgentRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    AWAITING_APPROVAL = "awaiting_approval"


class AgentRunRequest(BaseModel):
    agent_id: str = Field(default="memory_tools", min_length=1, max_length=80)
    task: str = Field(min_length=1, max_length=4000)
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)
    policy_tier: AgentPolicyTier = AgentPolicyTier.READ_ONLY
    approved: bool = False


class AgentToolCall(BaseModel):
    tool: str
    status: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None


class AgentRunResponse(BaseModel):
    run_id: str
    agent_id: str
    task: str
    status: AgentRunStatus
    policy_tier: AgentPolicyTier
    result: dict[str, Any] | None = None
    tool_calls: list[AgentToolCall] = Field(default_factory=list)
    message: str = ""
