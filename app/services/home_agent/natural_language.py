"""Deterministic natural-language routing for Home Agent physical-memory questions.

This module intentionally recognizes only bounded, explainable query shapes. Unknown
language fails closed instead of guessing an object or location.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


TimeScope = Literal["today", "yesterday", "this_morning"]


@dataclass(frozen=True, slots=True)
class HomeQueryIntent:
    kind: Literal["where_is", "before_location", "location_history"]
    object_name: str
    location: str | None = None
    time_scope: TimeScope | None = None


_BEFORE_PATTERNS = (
    re.compile(r"^where (?:was|were) (?:my |the )?(?P<object>.+?) before (?:i (?:left|put|placed) (?:it|them) (?:in|at|on) |(?:it|they) (?:was|were) (?:in|at|on) |)(?:the )?(?P<location>.+?)\??$", re.IGNORECASE),
    re.compile(r"^where (?:was|were) (?:my |the )?(?P<object>.+?) before (?:the )?(?P<location>.+?)\??$", re.IGNORECASE),
)
_TIME_SCOPE_PATTERN = r"today|yesterday|this morning"
_HISTORY_PATTERN = re.compile(
    rf"^where (?:has|have) (?:my |the )?(?P<object>.+?) been(?: (?P<time_scope>{_TIME_SCOPE_PATTERN}))?\??$",
    re.IGNORECASE,
)
_LAST_SEEN_PATTERN = re.compile(
    rf"^where did i last see (?:my |the )?(?P<object>.+?)(?: (?P<time_scope>{_TIME_SCOPE_PATTERN}))?\??$",
    re.IGNORECASE,
)
_WHERE_PATTERN = re.compile(
    rf"^where (?:is|are|was|were) (?:my |the )?(?P<object>.+?)(?: (?P<time_scope>{_TIME_SCOPE_PATTERN}))?\??$",
    re.IGNORECASE,
)


def _clean(value: str) -> str:
    return " ".join(value.strip().split()).rstrip("?.!").strip()


def _time_scope(match: re.Match[str]) -> TimeScope | None:
    value = match.group("time_scope")
    if value is None:
        return None
    normalized = value.lower()
    if normalized == "this morning":
        return "this_morning"
    return normalized  # type: ignore[return-value]  # regex restricts this to today|yesterday


def parse_home_query(text: str) -> HomeQueryIntent | None:
    """Parse a bounded Home/Jarvis physical-memory question without an LLM."""
    normalized = " ".join(text.strip().split())
    if not normalized:
        return None

    for pattern in _BEFORE_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match:
            object_name = _clean(match.group("object"))
            location = _clean(match.group("location"))
            if object_name and location:
                return HomeQueryIntent(kind="before_location", object_name=object_name, location=location)

    match = _HISTORY_PATTERN.fullmatch(normalized)
    if match:
        object_name = _clean(match.group("object"))
        if object_name:
            return HomeQueryIntent(kind="location_history", object_name=object_name, time_scope=_time_scope(match))

    for pattern in (_LAST_SEEN_PATTERN, _WHERE_PATTERN):
        match = pattern.fullmatch(normalized)
        if match:
            object_name = _clean(match.group("object"))
            if object_name:
                return HomeQueryIntent(kind="where_is", object_name=object_name, time_scope=_time_scope(match))
    return None
