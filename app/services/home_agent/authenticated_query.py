"""Authenticated identity boundary for Home Agent physical-memory queries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.models.user import UserPublic

from .query_service import BeforeLocationAnswer, HomeAgentQueryService, MovementEvent, WhereAnswer
from .physical_memory import ObjectSighting


@dataclass(frozen=True, slots=True)
class AuthenticatedHomeAgentQuery:
    """Bind all physical-memory reads to an already-authenticated user.

    Public callers never provide a tenant/user identifier. The boundary accepts
    a resolved ``UserPublic`` from the authentication layer and injects that
    identity into the underlying tenant-scoped query service.
    """

    service: HomeAgentQueryService
    user: UserPublic

    def where_is(self, *, object_name: str, min_confidence: float = 0.5) -> WhereAnswer | None:
        return self.service.where_is(user_id=self.user.user_id, object_name=object_name, min_confidence=min_confidence)

    def history(self, *, object_name: str, min_confidence: float = 0.0, limit: int = 20) -> list[ObjectSighting]:
        return self.service.history(user_id=self.user.user_id, object_name=object_name, min_confidence=min_confidence, limit=limit)

    def movement_history(
        self,
        *,
        object_name: str,
        min_confidence: float = 0.5,
        limit: int = 20,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[MovementEvent]:
        """Return tenant-scoped movement history with optional trusted time bounds."""
        return self.service.movement_history(
            user_id=self.user.user_id,
            object_name=object_name,
            min_confidence=min_confidence,
            limit=limit,
            since=since,
            until=until,
        )

    def before_location(self, *, object_name: str, location: str, min_confidence: float = 0.5, limit: int = 20) -> BeforeLocationAnswer | None:
        """Answer from authenticated tenant history only."""
        return self.service.before_location(
            user_id=self.user.user_id,
            object_name=object_name,
            location=location,
            min_confidence=min_confidence,
            limit=limit,
        )
