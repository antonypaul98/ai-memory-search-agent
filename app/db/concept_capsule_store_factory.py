"""Selected persistence boundary for Memory Intelligence concept capsules.

Derived concept capsules follow the canonical memory backend so production does
not silently retain this intelligence aggregate only in SQLite.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from app.db.intelligence_store import IntelligenceStore
from app.db.postgres_concept_capsule_store import PostgresConceptCapsuleStore
from app.db.postgres_runtime import get_postgres_connection_factory


def get_concept_capsule_store(settings: Settings | None = None) -> Any:
    resolved = settings or get_settings()
    if resolved.memory_store_backend == "postgres":
        return PostgresConceptCapsuleStore(get_postgres_connection_factory(resolved))
    return IntelligenceStore(resolved)
