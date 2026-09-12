"""Selected persistence boundary for the knowledge graph."""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from app.db.knowledge_graph_store import KnowledgeGraphStore
from app.db.postgres_knowledge_graph_store import PostgresKnowledgeGraphStore
from app.db.postgres_runtime import get_postgres_connection_factory


def get_selected_knowledge_graph_store(settings: Settings | None = None) -> Any:
    resolved = settings or get_settings()
    if resolved.memory_store_backend == "postgres":
        return PostgresKnowledgeGraphStore(get_postgres_connection_factory(resolved))
    return KnowledgeGraphStore(resolved)
