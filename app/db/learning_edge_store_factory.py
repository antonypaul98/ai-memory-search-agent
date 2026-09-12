"""Selected persistence boundary for Memory Intelligence learning edges.

Learning relationships follow the canonical memory backend so production cannot
place memories in Postgres while silently retaining their derived learning graph
only in SQLite.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from app.db.intelligence_store import IntelligenceStore
from app.db.postgres_learning_edge_store import PostgresLearningEdgeStore
from app.db.postgres_runtime import get_postgres_connection_factory


def get_learning_edge_store(settings: Settings | None = None) -> Any:
    resolved = settings or get_settings()
    if resolved.memory_store_backend == "postgres":
        return PostgresLearningEdgeStore(get_postgres_connection_factory(resolved))
    return IntelligenceStore(resolved)
