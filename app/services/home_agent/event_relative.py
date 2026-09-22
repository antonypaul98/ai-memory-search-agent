"""Evidence-backed event-relative physical-memory queries."""
from __future__ import annotations

from datetime import datetime, timezone

from .authenticated_query import AuthenticatedHomeAgentQuery
from .query_service import WhereAnswer


def where_before_latest_departure(
    *, query: AuthenticatedHomeAgentQuery, object_name: str,
    min_confidence: float = 0.5, limit: int = 100,
) -> WhereAnswer | None:
    """Return the newest object sighting strictly before a verified departure.

    The departure resolver and object history are both scoped to the authenticated
    tenant. If the backing store cannot resolve a qualified departure, fail closed.
    """
    resolver = getattr(query.service._store, "latest_presence_event", None)
    if not callable(resolver):
        return None
    departure = resolver(
        user_id=query.user.user_id,
        kind="home_departure",
        min_confidence=min_confidence,
    )
    if departure is None:
        return None
    return query.service.where_is_between(
        user_id=query.user.user_id,
        object_name=object_name,
        since=datetime(1970, 1, 1, tzinfo=timezone.utc),
        until=departure.occurred_at_utc,
        min_confidence=min_confidence,
        limit=max(1, min(limit, 100)),
    )
