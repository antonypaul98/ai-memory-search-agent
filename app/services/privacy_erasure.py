"""Production tenant-erasure orchestration for privacy controls."""
from __future__ import annotations

from typing import Any

from app.config import Settings
from app.db.account_erasure_fence import AccountErasureFence
from app.db.home_physical_privacy import delete_user_home_physical_data
from app.db.intelligence_privacy import delete_user_intelligence
from app.db.knowledge_graph_privacy import delete_user_graph
from app.db.postgres_agent_runtime_store import PostgresAgentRuntimeStore
from app.db.postgres_auth_store import PostgresAuthStore
from app.db.postgres_capture_store import PostgresCaptureStore
from app.db.postgres_event_store import PostgresEventStore
from app.db.postgres_feedback_privacy import delete_user_feedback_data
from app.db.postgres_model_usage_ledger import PostgresModelUsageLedger
from app.db.postgres_oauth_token_store import PostgresOAuthTokenStore
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.production_storage_profile import is_complete_postgres_profile
from app.services.home_agent.capture_registry import CaptureSessionRegistry
from app.services.privacy_service import PrivacyService


def delete_production_user_data(
    settings: Settings,
    *,
    user_id: str,
    privacy_service: PrivacyService | None = None,
    capture_registry: CaptureSessionRegistry | None = None,
) -> dict[str, Any]:
    """Delete one tenant's production data after durably fencing new work.

    The durable fence is installed before any deletion starts and intentionally
    survives partial failure/retry. This prevents agent and other fence-aware
    producers from recreating tenant state while erasure is in progress.
    """

    owner = str(user_id or "").strip()
    if not owner:
        raise ValueError("user_id is required")
    if not is_complete_postgres_profile(settings):
        raise RuntimeError("full user-data erasure requires complete Postgres profile")

    service = privacy_service or PrivacyService(settings)
    connection_factory = get_postgres_connection_factory(settings)

    # This must be first: a failed/partial erasure remains fail-closed on retry.
    AccountErasureFence(connection_factory).fence(user_id=owner)

    # Revoke authenticated/connector ingress and erase persisted agent execution
    # history before deleting canonical data. The durable fence prevents new
    # fence-aware work while these security credentials are being removed.
    oauth_tokens_deleted = 0
    if callable(connection_factory):
        PostgresAuthStore(settings, connection_factory).revoke_all_sessions(owner)
        PostgresAgentRuntimeStore(connection_factory).delete_for_user(user_id=owner)
        oauth_tokens_deleted = PostgresOAuthTokenStore(connection_factory).delete_for_user(user_id=owner)

    capture_sessions_revoked = (
        capture_registry.revoke_for_user(user_id=owner) if capture_registry is not None else 0
    )
    capture_payloads_deleted = PostgresCaptureStore(connection_factory).delete_for_user(user_id=owner)

    memory_result = service.delete_all_memories(user_id=owner)
    feedback_counts = delete_user_feedback_data(connection_factory, user_id=owner)
    model_usage_deleted = PostgresModelUsageLedger(connection_factory).delete_user_data(user_id=owner)
    activity_deleted = PostgresEventStore(connection_factory).delete_user_data(user_id=owner)
    graph_deleted = delete_user_graph(settings, user_id=owner)
    intelligence_deleted = delete_user_intelligence(connection_factory, user_id=owner)
    home_physical_deleted = delete_user_home_physical_data(connection_factory, user_id=owner)
    errors = list(memory_result.get("errors") or [])
    return {
        "deleted": not errors,
        "account_fenced": True,
        "oauth_tokens_deleted": oauth_tokens_deleted,
        "capture_sessions_revoked": capture_sessions_revoked,
        "capture_payloads_deleted": capture_payloads_deleted,
        "memory_deleted_count": int(memory_result.get("deleted_count") or 0),
        "memory_errors": errors,
        "feedback_deleted": feedback_counts,
        "model_usage_deleted": model_usage_deleted,
        "activity_deleted": activity_deleted,
        "graph_deleted": graph_deleted,
        "intelligence_deleted": intelligence_deleted,
        "home_physical_deleted": home_physical_deleted,
    }