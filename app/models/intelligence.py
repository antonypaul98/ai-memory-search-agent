"""Typed models for the V1-3 Memory Intelligence Layer."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.models.video import SearchResultItem


class TopicCategory(str, Enum):
    TOPIC = "topic"
    TECHNOLOGY = "technology"
    FRAMEWORK = "framework"
    LANGUAGE = "language"
    COMPANY = "company"
    PRODUCT = "product"
    PROJECT = "project"
    CONCEPT_CLUSTER = "concept_cluster"


class LearningRelation(str, Enum):
    EXPLAINS = "explains"
    EXPANDS = "expands"
    CONTRADICTS = "contradicts"
    ASSUMES = "assumes"
    SAME_TOPIC = "same_topic"
    SAME_CREATOR = "same_creator"


class TimelineMode(str, Enum):
    RECENTLY_LEARNED = "recently_learned"
    FIRST_LEARNED = "first_learned"
    MOST_REVISITED = "most_revisited"
    RECENTLY_SAVED = "recently_saved"
    TOPIC_EVOLUTION = "topic_evolution"


class RoadmapLevel(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class ExplanationBlock(BaseModel):
    """Why an answer or hit was returned — always grounded in stored evidence."""

    why: str
    matching_chunks: list[str] = Field(default_factory=list)
    matching_metadata: list[str] = Field(default_factory=list)
    matched_entities: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1, default=0.0)
    alternative_video_ids: list[str] = Field(default_factory=list)
    related_video_ids: list[str] = Field(default_factory=list)
    search_path: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class IntelligenceHit(BaseModel):
    result: SearchResultItem
    explanation: ExplanationBlock


class NaturalRetrieveResponse(BaseModel):
    query: str
    results: list[IntelligenceHit]
    search_path: list[str] = Field(default_factory=list)
    elapsed_ms: float = 0.0


class TopicProfile(BaseModel):
    topic_id: str
    name: str
    normalized_name: str
    category: TopicCategory
    summary: str = ""
    memory_count: int = 0
    video_ids: list[str] = Field(default_factory=list)
    first_seen_at: str
    last_seen_at: str
    evidence: list[str] = Field(default_factory=list)


class TopicListResponse(BaseModel):
    topics: list[TopicProfile]
    total: int


class TimelineEntry(BaseModel):
    video_id: str
    title: str
    channel: str = ""
    url: str = ""
    saved_at: str | None = None
    published_at: str | None = None
    topics: list[str] = Field(default_factory=list)
    view_count: int = 0
    search_count: int = 0
    reason: str = Field(description="Why this entry appears for the requested mode.")


class TimelineResponse(BaseModel):
    mode: TimelineMode
    topic: str | None = None
    entries: list[TimelineEntry]


class LearningEdge(BaseModel):
    edge_id: str
    source_video_id: str
    target_video_id: str
    relation: LearningRelation
    strength: float = Field(ge=0, le=1)
    evidence: str
    evidence_refs: list[str] = Field(default_factory=list)
    source_title: str = ""
    target_title: str = ""


class LearningGraphResponse(BaseModel):
    video_id: str | None = None
    topic: str | None = None
    edges: list[LearningEdge]
    node_count: int = 0


class RoadmapStep(BaseModel):
    level: RoadmapLevel
    video_id: str
    title: str
    channel: str = ""
    url: str = ""
    duration_sec: float | None = None
    reason: str
    completed: bool = True
    evidence: list[str] = Field(default_factory=list)


class LearningRoadmap(BaseModel):
    topic: str
    beginner: list[RoadmapStep] = Field(default_factory=list)
    intermediate: list[RoadmapStep] = Field(default_factory=list)
    advanced: list[RoadmapStep] = Field(default_factory=list)
    missing_prerequisites: list[str] = Field(default_factory=list)
    recommended_order: list[str] = Field(default_factory=list)
    already_completed: list[str] = Field(default_factory=list)
    suggested_next: list[RoadmapStep] = Field(default_factory=list)
    evidence_only: bool = True


class ConceptCapsule(BaseModel):
    capsule_id: str
    name: str
    normalized_name: str
    summary: str = ""
    key_memories: list[str] = Field(default_factory=list)
    related_creators: list[str] = Field(default_factory=list)
    topic_ids: list[str] = Field(default_factory=list)
    learning_progress: float = Field(ge=0, le=1, default=0.0)
    memory_count: int = 0
    updated_at: str


class ConceptCapsuleListResponse(BaseModel):
    capsules: list[ConceptCapsule]
    total: int


class DuplicateKnowledgeItem(BaseModel):
    video_id_a: str
    video_id_b: str
    title_a: str = ""
    title_b: str = ""
    relationship: str
    diversity_score: float = Field(
        ge=0,
        le=1,
        description="1 = highly diverse explanations; 0 = near-identical.",
    )
    shared_topics: list[str] = Field(default_factory=list)
    evidence: str


class DuplicateKnowledgeResponse(BaseModel):
    items: list[DuplicateKnowledgeItem]
    average_diversity: float = 0.0


class CreatorProfile(BaseModel):
    creator_id: str
    name: str
    normalized_name: str = ""
    channel_id: str = ""
    video_count: int = 0
    topics_covered: list[str] = Field(default_factory=list)
    average_depth_sec: float = 0.0
    beginner_friendliness: float = Field(
        ge=0,
        le=1,
        description="Share of saved videos tagged beginner / intro keywords.",
    )
    advanced_coverage: float = Field(
        ge=0,
        le=1,
        description="Share of saved videos tagged advanced / deep keywords.",
    )
    overlap_topics: list[str] = Field(default_factory=list)
    related_creators: list[str] = Field(default_factory=list)
    most_watched_video_id: str | None = None
    most_useful_video_id: str | None = None
    view_count: int = 0
    helpful_count: int = 0
    evidence: list[str] = Field(default_factory=list)


class CreatorListResponse(BaseModel):
    creators: list[CreatorProfile]
    total: int


class InsightsDashboard(BaseModel):
    top_topics: list[TopicProfile] = Field(default_factory=list)
    most_saved_concepts: list[str] = Field(default_factory=list)
    most_searched_concepts: list[str] = Field(default_factory=list)
    forgotten_topics: list[TopicProfile] = Field(default_factory=list)
    learning_streak_days: int = 0
    knowledge_growth: list[dict] = Field(
        default_factory=list,
        description="[{date, entity_count}] derived from first_seen timestamps.",
    )
    memory_growth: list[dict] = Field(
        default_factory=list,
        description="[{date, memory_count}] derived from saved_at timestamps.",
    )
    total_memories: int = 0
    total_topics: int = 0
    total_creators: int = 0
    total_learning_edges: int = 0
