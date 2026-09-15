"""Production tenant-erasure orchestration for privacy controls."""
from __future__ import annotations

from typing import Any

from app.config import Settings
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
    """Delete one tenant's memory, feedback and model-usage domains in the full Postgres profile.

    This intentionally fails closed outside the complete production profile instead
    of claiming a full-account erasure while a relational domain could remain on a
    legacy backend. Memory deletion is best-effort per canonical memory; feedback
    deletion is still attempted so a later retry only has to finish any reported
    memory failures.
    """

    if not str(user_id).strip():
        raise ValueError("user_id is required")
    if not is_complete_postgres_profile(settings):
        raise RuntimeError("full user-data erasure requires complete Postgres profile")

    service = privacy_service or PrivacyService(settings)
    memory_result = service.delete_all_memories(user_id=user_id)
    feedback_counts = delete_user_feedback_data(
        get_postgres_connection_factory(settings),
        user_id=user_id,
    )
    model_usage_deleted = PostgresModelUsageLedger(
        get_postgres_connection_factory(settings)
    ).delete_user_data(user_id=user_id)
    errors = list(memory_result.get("errors") or [])
    return {
        "deleted": not errors,
        "memory_deleted_count": int(memory_result.get("deleted_count") or 0),
        "memory_errors": errors,
        "feedback_deleted": feedback_counts,
        "model_usage_deleted": model_usage_deleted,
    }
