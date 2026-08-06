"""
Detect ambiguous questions and offer clarifying choices before answering.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.enrichment_service import _tokenize

_WIRING_DOMAINS: dict[str, list[str]] = {
    "House wiring": ["outlet", "breaker", "120v", "240v", "gfci", "electrical panel", "wire nut"],
    "Car wiring": ["automotive", "12v", "fuse box", "harness", "battery terminal", "ground wire"],
    "Tesla wiring": ["tesla", "high voltage", "ev", "charge port", "battery pack"],
    "PC wiring": ["psu", "24-pin", "cpu power", "front panel", "sata", "motherboard header", "pc build"],
}

_SAFETY_PATTERN = re.compile(r"\b(safety|precaution|precautions|warning|hazard|risk)\b", re.I)
_WIRING_PATTERN = re.compile(r"\bwiring\b", re.I)


@dataclass(frozen=True)
class ClarificationOption:
    id: str
    label: str


@dataclass(frozen=True)
class ClarificationResult:
    needs_clarification: bool
    prompt: str = ""
    options: list[ClarificationOption] | None = None


def analyze_clarification(question: str, chunks: list[dict]) -> ClarificationResult:
    """Return clarifying options when multiple memory domains could answer."""
    if not chunks:
        return ClarificationResult(needs_clarification=False)

    if _WIRING_PATTERN.search(question) or (
        _SAFETY_PATTERN.search(question) and _question_is_ambiguous(question, chunks)
    ):
        options = _build_wiring_options(chunks)
        if len(options) >= 2:
            return ClarificationResult(
                needs_clarification=True,
                prompt="Multiple saved memories could answer this. Which context should I use?",
                options=options,
            )

    topic_options = _build_topic_options(question, chunks)
    if len(topic_options) >= 2:
        return ClarificationResult(
            needs_clarification=True,
            prompt="I found multiple relevant memories. Which should I focus on?",
            options=topic_options,
        )

    return ClarificationResult(needs_clarification=False)


def filter_chunks_by_choice(chunks: list[dict], choice: str) -> list[dict]:
    """Keep chunks that best match the user's clarification selection."""
    if not choice or choice.lower() == "compare all":
        return chunks

    choice_lower = choice.lower()
    domain_terms = []
    for label, terms in _WIRING_DOMAINS.items():
        if label.lower() == choice_lower or choice_lower in label.lower():
            domain_terms = terms
            break

    if domain_terms:
        filtered = [
            chunk
            for chunk in chunks
            if _chunk_matches_terms(chunk, domain_terms + [choice_lower])
        ]
        if filtered:
            return filtered

    filtered = [chunk for chunk in chunks if _chunk_matches_terms(chunk, [choice_lower])]
    return filtered or chunks


def _build_wiring_options(chunks: list[dict]) -> list[ClarificationOption]:
    scores: dict[str, float] = {label: 0.0 for label in _WIRING_DOMAINS}
    for chunk in chunks:
        corpus = " ".join(
            [
                chunk.get("matched_text", ""),
                chunk.get("title", ""),
                chunk.get("description", ""),
            ]
        ).lower()
        for label, terms in _WIRING_DOMAINS.items():
            hits = sum(1 for term in terms if term in corpus)
            scores[label] += hits + chunk.get("relevance_score", 0)

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    options = [
        ClarificationOption(id=label.lower().replace(" ", "_"), label=label)
        for label, score in ranked
        if score > 0
    ][:4]
    if len(options) >= 2:
        options.append(ClarificationOption(id="compare_all", label="Compare all"))
    return options


def _build_topic_options(question: str, chunks: list[dict]) -> list[ClarificationOption]:
    by_video: dict[str, dict] = {}
    for chunk in chunks:
        video_id = chunk.get("video_id") or ""
        if not video_id:
            continue
        existing = by_video.get(video_id)
        if existing is None or chunk["relevance_score"] > existing["relevance_score"]:
            by_video[video_id] = chunk

    ranked = sorted(by_video.values(), key=lambda c: c["relevance_score"], reverse=True)
    if len(ranked) < 2:
        return []

    top_score = ranked[0]["relevance_score"]
    second_score = ranked[1]["relevance_score"]
    if top_score - second_score > 0.15:
        return []

    options = [
        ClarificationOption(
            id=hit["video_id"],
            label=hit.get("title", hit["video_id"])[:60],
        )
        for hit in ranked[:4]
    ]
    options.append(ClarificationOption(id="compare_all", label="Compare all"))
    return options


def _question_is_ambiguous(question: str, chunks: list[dict]) -> bool:
    terms = set(_tokenize(question))
    if "wiring" in terms or "electrical" in terms:
        return True
    domains = 0
    for chunk in chunks[:6]:
        corpus = chunk.get("matched_text", "").lower()
        if any(term in corpus for terms in _WIRING_DOMAINS.values() for term in terms):
            domains += 1
    return domains >= 2


def _chunk_matches_terms(chunk: dict, terms: list[str]) -> bool:
    corpus = " ".join(
        [
            chunk.get("matched_text", ""),
            chunk.get("title", ""),
            chunk.get("description", ""),
            chunk.get("channel", ""),
        ]
    ).lower()
    return any(term in corpus for term in terms)
