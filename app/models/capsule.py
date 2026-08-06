"""Structured Memory Capsule schema for hierarchical retrieval."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MemorySection(BaseModel):
    title: str = ""
    summary: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    keywords: list[str] = Field(default_factory=list)


class MemoryCapsule(BaseModel):
    video_id: str
    title: str = ""
    one_line_memory: str = ""
    short_summary: str = ""
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    tools_or_components: list[str] = Field(default_factory=list)
    procedures: list[str] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)
    difficulty: str = "unknown"
    content_style: list[str] = Field(default_factory=list)
    creator: str = ""
    duration: float = 0.0
    upload_date: str = ""
    save_reason: str = ""
    user_goal: str = ""
    sections: list[MemorySection] = Field(default_factory=list)


class StructuredAnswer(BaseModel):
    answer_markdown: str
    answer_type: str = "general"
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: str = "medium"
    missing_information: list[str] = Field(default_factory=list)
