"""Selected persistence boundary for Memory Intelligence events."""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from app.db.intelligence_store import IntelligenceStore
from app.db.postgres_intelligence_event_store import PostgresIntelligenceEventStore
from app.db.postgres_runtime import get_postgres_connection_factory


def get_intelligence_event_store(settings: Settings | None = None) -> Any:
    resolved = settings or get_settings()
    if resolved.memory_store_backend == "postgres":
        return PostgresIntelligenceEventStore(get_postgres_connection_factory(resolved))
    return IntelligenceStore(resolved)
