"""Production tenant-erasure orchestration for privacy controls."""
from __future__ import annotations

from typing import Any

from app.config import Settings
from app.db.home_physical_privacy import delete_user_home_physical_data
from app.db.intelligence_privacy import delete_user_intelligence
from app.db.knowledge_graph_privacy import delete_user_graph
from app.db.postgres_event_store import PostgresEventStore
from app.db.postgres_feedback_privacy import delete_user_feedback_data
from app.db.postgres_model_usage_ledger import PostgresModelUsageLedger
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.production_storage_profile import is_complete_postgres_profile
from app.services.privacy_service import PrivacyService


def delete_production_user_data(
    settings: Settings,
    *,
    user_id: str,
    privacy_service: PrivacyService | None = None,
) -> dict[str, Any]:
    """Delete one tenant's memory, feedback, usage, activity, graph, intelligence and Home physical data.

    This intentionally fails closed outside the complete production profile instead
    of claiming a full-account erasure while a relational domain could remain on a
    legacy backend. Memory deletion is best-effort per canonical memory; subsequent
    bounded domains are still attempted in sequence so a later retry can complete
    any remaining work.
    """

    if not str(user_id).strip():
        raise ValueError("user_id is required")
    if not is_complete_postgres_profile(settings):
        raise RuntimeError("full user-data erasure requires complete Postgres profile")

    service = privacy_service or PrivacyService(settings)
    connection_factory = get_postgres_connection_factory(settings)
    memory_result = service.delete_all_memories(user_id=user_id)
    feedback_counts = delete_user_feedback_data(
        connection_factory,
        user_id=user_id,
    )
    model_usage_deleted = PostgresModelUsageLedger(
        connection_factory
    ).delete_user_data(user_id=user_id)
    activity_deleted = PostgresEventStore(
        connection_factory
    ).delete_user_data(user_id=user_id)
    graph_deleted = delete_user_graph(settings, user_id=user_id)
    intelligence_deleted = delete_user_intelligence(
        connection_factory,
        user_id=user_id,
    )
    home_physical_deleted = delete_user_home_physical_data(
        connection_factory,
        user_id=user_id,
    )
    errors = list(memory_result.get("errors") or [])
    return {
        "deleted": not errors,
        "memory_deleted_count": int(memory_result.get("deleted_count") or 0),
        "memory_errors": errors,
        "feedback_deleted": feedback_counts,
        "model_usage_deleted": model_usage_deleted,
        "activity_deleted": activity_deleted,
        "graph_deleted": graph_deleted,
        "intelligence_deleted": intelligence_deleted,
        "home_physical_deleted": home_physical_deleted,
    }
