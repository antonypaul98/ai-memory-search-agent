"""Deterministic query intent routing for AHME."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class QueryType(str, Enum):
    EXACT_LOOKUP = "exact_lookup"
    LIST_COMPONENTS = "list_components"
    PROCEDURAL = "procedural"
    COMPARISON = "comparison"
    SUMMARY = "summary"
    RECOMMENDATION = "recommendation"
    REFLECTION = "reflection"
    AMBIGUOUS = "ambiguous"
    CROSS_VIDEO = "cross_video"


@dataclass(frozen=True)
class RouteDecision:
    query_types: list[QueryType]
    needs_clarification: bool
    video_top_k: int
    section_top_k: int
    evidence_top_k: int
    needs_detailed_evidence: bool
    allow_cache: bool
    answer_format: str
    confidence: float


_LIST = re.compile(r"\b(components?|parts?|tools?|requirements?|list|what do i need)\b", re.I)
_PROC = re.compile(r"\b(how\s+to|how\s+do|steps?|install|setup|guide)\b", re.I)
_COMPARE = re.compile(r"\b(compare|versus|vs\.?|difference|better)\b", re.I)
_SUMMARY = re.compile(r"\b(summarize|summary|overview|recap)\b", re.I)
_RECOMMEND = re.compile(r"\b(recommend|suggest|what should i watch|similar)\b", re.I)
_REFLECT = re.compile(r"\b(why did i save|saved because|my goal|reflection)\b", re.I)
_SAFETY = re.compile(r"\b(safety|precaution|wiring|hazard)\b", re.I)
_CROSS = re.compile(r"\b(across|both videos|all videos|compare videos|multiple)\b", re.I)


def route_query(question: str, *, settings=None) -> RouteDecision:
    from app.config import get_settings

    settings = settings or get_settings()
    types: list[QueryType] = []

    if _REFLECT.search(question):
        types.append(QueryType.REFLECTION)
    if _RECOMMEND.search(question):
        types.append(QueryType.RECOMMENDATION)
    if _COMPARE.search(question) or _CROSS.search(question):
        types.append(QueryType.COMPARISON if _COMPARE.search(question) else QueryType.CROSS_VIDEO)
    if _LIST.search(question):
        types.append(QueryType.LIST_COMPONENTS)
    if _PROC.search(question):
        types.append(QueryType.PROCEDURAL)
    if _SUMMARY.search(question):
        types.append(QueryType.SUMMARY)
    if _SAFETY.search(question):
        types.append(QueryType.AMBIGUOUS)
    if not types:
        types.append(QueryType.EXACT_LOOKUP)

    needs_clarification = QueryType.AMBIGUOUS in types
    needs_evidence = QueryType.PROCEDURAL in types or QueryType.LIST_COMPONENTS in types
    allow_cache = QueryType.AMBIGUOUS not in types and QueryType.REFLECTION not in types

    if QueryType.CROSS_VIDEO in types or QueryType.COMPARISON in types:
        video_k = settings.video_top_k
        section_k = settings.section_top_k
        evidence_k = settings.evidence_top_k
        answer_format = "comparison_table"
    elif QueryType.LIST_COMPONENTS in types:
        video_k = min(settings.video_top_k, 2)
        section_k = settings.section_top_k
        evidence_k = settings.evidence_top_k
        answer_format = "bullet_list"
    elif QueryType.SUMMARY in types:
        video_k = 2
        section_k = 4
        evidence_k = 6
        answer_format = "summary_bullets"
    else:
        video_k = settings.video_top_k
        section_k = settings.section_top_k
        evidence_k = settings.evidence_top_k
        answer_format = "concise"

    return RouteDecision(
        query_types=types,
        needs_clarification=needs_clarification,
        video_top_k=video_k,
        section_top_k=section_k,
        evidence_top_k=evidence_k,
        needs_detailed_evidence=needs_evidence,
        allow_cache=allow_cache,
        answer_format=answer_format,
        confidence=0.85 if len(types) == 1 else 0.65,
    )
