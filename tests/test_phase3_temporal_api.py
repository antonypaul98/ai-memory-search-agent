"""API-level regression tests for Phase 3 temporal knowledge filters."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.api.routes.knowledge import entity_relations, graph_neighbors
from app.models.knowledge_graph import GraphQueryResponse
from app.models.user import UserPublic


def _user() -> UserPublic:
    return UserPublic(user_id="tenant-a", display_name="Tenant A")


def test_entity_relations_normalizes_at_timestamp_to_utc() -> None:
    graph = MagicMock()
    graph.relations_for_entity.return_value = GraphQueryResponse(entities=[MagicMock()])
    at = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)

    entity_relations(
        "entity-1",
        direction="both",
        at_time=at,
        user=_user(),
        graph=graph,
    )

    graph.relations_for_entity.assert_called_once_with(
        "entity-1",
        user_id="tenant-a",
        direction="both",
        at_time="2026-01-15T12:00:00+00:00",
    )


def test_graph_neighbors_propagates_temporal_filter_and_tenant() -> None:
    graph = MagicMock()
    graph.neighbors.return_value = GraphQueryResponse(entities=[MagicMock()])
    at = datetime(2026, 2, 1, 7, 30, tzinfo=timezone.utc)

    graph_neighbors(
        entity_id="entity-2",
        depth=2,
        at_time=at,
        user=_user(),
        graph=graph,
    )

    graph.neighbors.assert_called_once_with(
        "entity-2",
        user_id="tenant-a",
        depth=2,
        at_time="2026-02-01T07:30:00+00:00",
    )
