"""Authenticated execution for bounded Home/Jarvis natural-language queries."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .authenticated_query import AuthenticatedHomeAgentQuery
from .natural_language import parse_home_query
from .query_service import BeforeLocationAnswer, MovementEvent, WhereAnswer


@dataclass(frozen=True, slots=True)
class NaturalLanguageQueryResult:
    """Typed result that keeps parsing/execution failures explicit."""

    status: Literal["answered", "unsupported", "not_found"]
    kind: Literal["where_is", "before_location", "location_history"] | None = None
    answer: WhereAnswer | BeforeLocationAnswer | list[MovementEvent] | None = None


def execute_home_query(
    *,
    text: str,
    query: AuthenticatedHomeAgentQuery,
    min_confidence: float = 0.5,
    limit: int = 20,
) -> NaturalLanguageQueryResult:
    """Parse and execute one bounded question using authenticated tenant identity only."""
    intent = parse_home_query(text)
    if intent is None:
        return NaturalLanguageQueryResult(status="unsupported")

    if intent.kind == "where_is":
        answer = query.where_is(
            object_name=intent.object_name,
            min_confidence=min_confidence,
        )
    elif intent.kind == "location_history":
        answer = query.movement_history(
            object_name=intent.object_name,
            min_confidence=min_confidence,
            limit=limit,
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
