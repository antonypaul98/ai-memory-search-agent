"""Knowledge graph query API routes."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.auth import get_current_user
from app.config import Settings, get_settings
from app.db.memory_store import MemoryStore, get_memory_store
from app.models.knowledge_graph import EntityType, GraphEntity, GraphQueryResponse
from app.models.user import UserPublic
from app.services.knowledge_graph_service import KnowledgeGraphService

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _graph(settings: Settings = Depends(get_settings)) -> KnowledgeGraphService:
    return KnowledgeGraphService(settings=settings)


def _memory_store(settings: Settings = Depends(get_settings)) -> MemoryStore:
    return get_memory_store(settings)


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


@router.get("/entities", response_model=list[GraphEntity])
def search_entities(
    q: str = Query(default="", max_length=200),
    entity_type: EntityType | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    user: UserPublic = Depends(get_current_user),
    graph: KnowledgeGraphService = Depends(_graph),
) -> list[GraphEntity]:
    return graph.search_entities(
        user_id=user.user_id,
        query=q,
        entity_type=entity_type,
        limit=limit,
    )


@router.get("/entities/{entity_id}", response_model=GraphEntity)
def get_entity(
    entity_id: str,
    user: UserPublic = Depends(get_current_user),
    graph: KnowledgeGraphService = Depends(_graph),
) -> GraphEntity:
    entity = graph.get_entity(entity_id, user_id=user.user_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found.")
    return entity


@router.get("/entities/{entity_id}/relations", response_model=GraphQueryResponse)
def entity_relations(
    entity_id: str,
    direction: str = Query(default="both", pattern="^(outgoing|incoming|both)$"),
    at_time: datetime | None = Query(default=None, alias="at"),
    user: UserPublic = Depends(get_current_user),
    graph: KnowledgeGraphService = Depends(_graph),
) -> GraphQueryResponse:
    response = graph.relations_for_entity(
        entity_id,
        user_id=user.user_id,
        direction=direction,
        at_time=_utc_iso(at_time),
    )
    if not response.entities:
        raise HTTPException(status_code=404, detail="Entity not found.")
    return response


@router.get("/graph/neighbors", response_model=GraphQueryResponse)
def graph_neighbors(
    entity_id: str = Query(..., min_length=1),
    depth: int = Query(default=1, ge=1, le=2),
    at_time: datetime | None = Query(default=None, alias="at"),
    user: UserPublic = Depends(get_current_user),
    graph: KnowledgeGraphService = Depends(_graph),
) -> GraphQueryResponse:
    response = graph.neighbors(
        entity_id,
        user_id=user.user_id,
        depth=depth,
        at_time=_utc_iso(at_time),
    )
    if not response.entities:
        raise HTTPException(status_code=404, detail="Entity not found.")
    return response


@router.get("/memories/{memory_id}/entities", response_model=list[GraphEntity])
def memory_entities(
    memory_id: str,
    user: UserPublic = Depends(get_current_user),
    graph: KnowledgeGraphService = Depends(_graph),
    store: MemoryStore = Depends(_memory_store),
) -> list[GraphEntity]:
    """List knowledge-graph entities linked to a universal memory."""
    entities = graph.entities_for_memory(memory_id, user_id=user.user_id)
    if not entities and not store.get(memory_id, user_id=user.user_id):
        raise HTTPException(status_code=404, detail="Memory not found.")
    return entities
