"""Selected persistence boundary for Memory Intelligence topics.

Topic aggregates follow the canonical memory backend so production cannot place
memories in Postgres while continuing to write their derived topic state only to
SQLite. Other IntelligenceStore aggregates are migrated independently.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from app.db.intelligence_store import IntelligenceStore
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.postgres_topic_store import PostgresTopicStore


def get_topic_store(settings: Settings | None = None) -> Any:
    resolved = settings or get_settings()
    if resolved.memory_store_backend == "postgres":
        return PostgresTopicStore(get_postgres_connection_factory(resolved))
    return IntelligenceStore(resolved)
