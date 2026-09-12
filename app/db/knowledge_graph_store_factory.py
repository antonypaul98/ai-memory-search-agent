"""Selected persistence boundary for the knowledge graph."""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from app.db.knowledge_graph_store import KnowledgeGraphStore
from app.db.postgres_knowledge_graph_store import PostgresKnowledgeGraphStore
from app.db.postgres_runtime import get_postgres_connection_factory


def get_selected_knowledge_graph_store(settings: Settings | None = None) -> Any:
    resolved = settings or get_settings()
    # Some focused callers/tests pass a partial settings-shaped object. Normalize
    # it through Settings so backend defaults and required SQLite paths remain
    # consistent with the application's real configuration rather than creating
    # an incompletely configured store.
    if not isinstance(resolved, Settings):
        resolved = Settings(**vars(resolved))
    if resolved.memory_store_backend == "postgres":
        return PostgresKnowledgeGraphStore(get_postgres_connection_factory(resolved))
    return KnowledgeGraphStore(resolved)
