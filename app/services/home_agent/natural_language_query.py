"""Authenticated execution for bounded Home/Jarvis natural-language queries."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from .authenticated_query import AuthenticatedHomeAgentQuery
from .natural_language import parse_home_query
from .query_service import BeforeLocationAnswer, MovementEvent, WhereAnswer


@dataclass(frozen=True, slots=True)
class NaturalLanguageQueryResult:
    """Typed result that keeps parsing/execution failures explicit."""

    status: Literal["answered", "unsupported", "not_found"]
    kind: Literal["where_is", "before_location", "location_history"] | None = None
    answer: WhereAnswer | BeforeLocationAnswer | list[MovementEvent] | None = None


def _local_day_bounds(*, timezone_name: str, day_offset: int = 0, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return a UTC half-open interval for a trusted local calendar day."""
    zone = ZoneInfo(timezone_name)
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local_date = instant.astimezone(zone).date() + timedelta(days=day_offset)
    local_start = datetime.combine(local_date, time.min, tzinfo=zone)
    local_end = datetime.combine(local_date + timedelta(days=1), time.min, tzinfo=zone)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)


def _today_bounds(*, timezone_name: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return the UTC half-open interval covering today in a trusted IANA timezone."""
    return _local_day_bounds(timezone_name=timezone_name, now=now)


def execute_home_query(
    *,
    text: str,
    query: AuthenticatedHomeAgentQuery,
    min_confidence: float = 0.5,
    limit: int = 20,
    timezone_name: str = "UTC",
    now: datetime | None = None,
) -> NaturalLanguageQueryResult:
    """Parse and execute one bounded question using authenticated tenant identity only.

    ``timezone_name`` is retained for call-site compatibility but relative-time
    execution derives timezone from the authenticated user, never caller input.
    """
    intent = parse_home_query(text)
    if intent is None:
        return NaturalLanguageQueryResult(status="unsupported")

    if intent.kind == "where_is":
        if intent.time_scope == "today":
            answer = query.where_is_today(
                object_name=intent.object_name,
                min_confidence=min_confidence,
                now=now,
                limit=max(limit, 100),
            )
        elif intent.time_scope == "yesterday":
            since, until = _local_day_bounds(timezone_name=query.user.timezone_name, day_offset=-1, now=now)
            history = query.movement_history(
                object_name=intent.object_name,
                min_confidence=min_confidence,
                limit=max(limit, 100),
                since=since,
                until=until,
            )
            answer = history[-1] if history else None
        else:
            answer = query.where_is(
                object_name=intent.object_name,
                min_confidence=min_confidence,
            )
    elif intent.kind == "location_history":
        since = until = None
        if intent.time_scope == "today":
            since, until = _today_bounds(timezone_name=query.user.timezone_name, now=now)
        elif intent.time_scope == "yesterday":
            since, until = _local_day_bounds(timezone_name=query.user.timezone_name, day_offset=-1, now=now)
        answer = query.movement_history(
            object_name=intent.object_name,
            min_confidence=min_confidence,
            limit=limit,
            since=since,
            until=until,
        )
    else:
        if intent.location is None:  # defensive invariant for typed parser output
            return NaturalLanguageQueryResult(status="unsupported")
        answer = query.before_location(
            object_name=intent.object_name,
            location=intent.location,
            min_confidence=min_confidence,
            limit=limit,
        )

    if not answer:
        return NaturalLanguageQueryResult(status="not_found", kind=intent.kind)
    return NaturalLanguageQueryResult(status="answered", kind=intent.kind, answer=answer)
