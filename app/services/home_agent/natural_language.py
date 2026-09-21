"""Deterministic natural-language routing for Home Agent physical-memory questions.

This module intentionally recognizes only bounded, explainable query shapes. Unknown
language fails closed instead of guessing an object or location.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class HomeQueryIntent:
    kind: Literal["where_is", "before_location", "location_history"]
    object_name: str
    location: str | None = None
    time_scope: Literal["today"] | None = None


_BEFORE_PATTERNS = (
    re.compile(r"^where (?:was|were) (?:my |the )?(?P<object>.+?) before (?:i (?:left|put|placed) (?:it|them) (?:in|at|on) |(?:it|they) (?:was|were) (?:in|at|on) |)(?:the )?(?P<location>.+?)\??$", re.IGNORECASE),
    re.compile(r"^where (?:was|were) (?:my |the )?(?P<object>.+?) before (?:the )?(?P<location>.+?)\??$", re.IGNORECASE),
)
_HISTORY_PATTERN = re.compile(
    r"^where (?:has|have) (?:my |the )?(?P<object>.+?) been(?P<today> today)?\??$",
    re.IGNORECASE,
)
_WHERE_PATTERN = re.compile(
    r"^where (?:is|are) (?:my |the )?(?P<object>.+?)(?P<today> today)?\??$",
    re.IGNORECASE,
)


def _clean(value: str) -> str:
    return " ".join(value.strip().split()).rstrip("?.!").strip()


def parse_home_query(text: str) -> HomeQueryIntent | None:
    """Parse a bounded Home/Jarvis physical-memory question without an LLM.

    Supported examples include ``Where are my keys?``, ``Where are my keys today?``,
    ``Where were my keys before the kitchen?``, ``Where were my keys before I left
    them in the kitchen?`` and ``Where have my keys been today?``. Unsupported or
    ambiguous text returns ``None``.
    """
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
            time_scope = "today" if match.group("today") else None
            return HomeQueryIntent(kind="location_history", object_name=object_name, time_scope=time_scope)

    match = _WHERE_PATTERN.fullmatch(normalized)
    if match:
        object_name = _clean(match.group("object"))
        if object_name:
            time_scope = "today" if match.group("today") else None
            return HomeQueryIntent(kind="where_is", object_name=object_name, time_scope=time_scope)
    return None
