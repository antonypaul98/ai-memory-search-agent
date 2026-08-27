"""Knowledge graph entity and relationship models."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class EntityType(str, Enum):
    """Supported graph entity types."""

    MEMORY = "memory"
    CONCEPT = "concept"
    PERSON = "person"
    COMPANY = "company"
    PROJECT = "project"
    TECHNOLOGY = "technology"
    CREATOR = "creator"
    TAG = "tag"


class RelationPredicate(str, Enum):
    """Typed edges in the knowledge graph."""

    MENTIONS = "mentions"
    AUTHORED_BY = "authored_by"
    TAGGED_WITH = "tagged_with"
    RELATED_TO = "related_to"
    PART_OF_PROJECT = "part_of_project"
    USES_TECHNOLOGY = "uses_technology"
    DERIVED_FROM = "derived_from"


class GraphEntity(BaseModel):
    entity_id: str
    user_id: str
    entity_type: EntityType
    name: str
    normalized_name: str
    aliases: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    created_at: str
    updated_at: str


class GraphRelation(BaseModel):
    relation_id: str
    user_id: str
    subject_entity_id: str
    predicate: RelationPredicate
    object_entity_id: str
    memory_id: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict = Field(default_factory=dict)
    valid_from: str | None = None
    valid_to: str | None = None
    created_at: str


class MemoryEntityLink(BaseModel):
    memory_id: str
    entity_id: str
    mention_context: str = ""
    start_time: float | None = None
    end_time: float | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class GraphNeighbor(BaseModel):
    entity: GraphEntity
    relation: GraphRelation
    direction: str = Field(description="'outgoing' or 'incoming'")


class GraphQueryResponse(BaseModel):
    entities: list[GraphEntity] = Field(default_factory=list)
    relations: list[GraphRelation] = Field(default_factory=list)
    neighbors: list[GraphNeighbor] = Field(default_factory=list)


class GraphEntityMergeRequest(BaseModel):
    source_entity_id: str = Field(min_length=1, max_length=200)


class GraphEntityMergeResult(BaseModel):
    entity: GraphEntity
    merged_source_entity_id: str
    rewired_memory_links: int = Field(ge=0)
    rewired_relations: int = Field(ge=0)
    collapsed_relations: int = Field(ge=0)
