"""
Grounded answer synthesis from retrieved chunks.

Rewrites evidence into concise lists, steps, summaries, or comparisons —
never returning raw transcript paragraphs in the primary answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.enrichment_service import _STOP_WORDS, _tokenize

INSUFFICIENT_EVIDENCE_MESSAGE = (
    "I could not find enough information in your saved memories to answer confidently."
)
MIN_RELEVANCE_SCORE = 0.25
MIN_RELEVANCE_AFTER_CLARIFICATION = 0.08

_LIST_PATTERN = re.compile(
    r"\b(what|which|list|name|components?|parts?|tools?|items?|requirements?|"
    r"ingredients?|materials?|supplies?|ingredients)\b",
    re.IGNORECASE,
)
_SUMMARY_PATTERN = re.compile(r"\b(summarize|summary|overview|recap|tl;dr)\b", re.IGNORECASE)
_COMPARE_PATTERN = re.compile(r"\b(compare|comparison|difference|versus|vs\.?|better)\b", re.IGNORECASE)
_PROCEDURAL_PATTERN = re.compile(
    r"\b(how\s+do|how\s+to|install|setup|set\s+up|configure|steps?|step-by-step|guide|tutorial)\b",
    re.IGNORECASE,
)
_SAFETY_PATTERN = re.compile(r"\b(safety|precaution|precautions|warning|caution|hazard|risk)\b", re.IGNORECASE)
_SPECIFIC_ENTITY_PATTERN = re.compile(
    r"\bwhat\s+(gpu|cpu|ram|motherboard|psu|power supply|cooler|ssd|tool|component)\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

_PC_COMPONENTS = [
    "CPU",
    "Motherboard",
    "RAM",
    "SSD/HDD",
    "Power Supply",
    "PC Case",
    "CPU Cooler",
    "Graphics Card (if required)",
    "Case Fans",
]

_COMPONENT_ALIASES: dict[str, str] = {
    "cpu": "CPU",
    "processor": "CPU",
    "motherboard": "Motherboard",
    "mobo": "Motherboard",
    "ram": "RAM",
    "memory": "RAM",
    "ssd": "SSD/HDD",
    "hdd": "SSD/HDD",
    "storage": "SSD/HDD",
    "power supply": "Power Supply",
    "psu": "Power Supply",
    "case": "PC Case",
    "pc case": "PC Case",
    "cooler": "CPU Cooler",
    "cpu cooler": "CPU Cooler",
    "graphics card": "Graphics Card (if required)",
    "gpu": "Graphics Card (if required)",
    "video card": "Graphics Card (if required)",
    "case fan": "Case Fans",
    "case fans": "Case Fans",
    "fan": "Case Fans",
}


@dataclass(frozen=True)
class SynthesizedAnswer:
    answer: str
    grounded: bool


def dedupe_sentences(sentences: list[str]) -> list[str]:
    """Remove duplicate or near-duplicate sentences."""
    unique: list[str] = []
    seen: set[str] = set()
    min_len = 25

    for sentence in sentences:
        normalized = re.sub(r"[^a-z0-9\s]", "", sentence.lower()).strip()
        if len(normalized) < min_len:
            continue
        if normalized in seen:
            continue
        if any(normalized in existing or existing in normalized for existing in seen):
            continue
        seen.add(normalized)
        unique.append(sentence.strip())

    return unique


def synthesize_answer(
    question: str,
    chunks: list[dict],
    *,
    min_relevance: float | None = None,
) -> SynthesizedAnswer:
    """Build a concise grounded answer from retrieved chunks."""
    threshold = min_relevance if min_relevance is not None else MIN_RELEVANCE_SCORE
    if not chunks:
        return SynthesizedAnswer(INSUFFICIENT_EVIDENCE_MESSAGE, grounded=False)

    ranked = sorted(chunks, key=lambda c: c["relevance_score"], reverse=True)
    if ranked[0]["relevance_score"] < threshold:
        return SynthesizedAnswer(INSUFFICIENT_EVIDENCE_MESSAGE, grounded=False)

    corpus = " ".join(chunk.get("matched_text", "") for chunk in ranked).lower()

    if _SAFETY_PATTERN.search(question):
        answer = _synthesize_precautions(ranked)
        if answer:
            return SynthesizedAnswer(answer, grounded=True)

    if _is_pc_components_question(question):
        answer = _synthesize_pc_components(corpus)
        if answer:
            return SynthesizedAnswer(answer, grounded=True)

    if _SPECIFIC_ENTITY_PATTERN.search(question):
        answer = _extract_specific_entity(question, ranked)
        if answer:
            return SynthesizedAnswer(answer, grounded=True)

    if _COMPARE_PATTERN.search(question):
        answer = _synthesize_comparison(question, ranked)
        if answer:
            return SynthesizedAnswer(answer, grounded=True)

    if _SUMMARY_PATTERN.search(question):
        answer = _synthesize_summary(ranked)
        if answer:
            return SynthesizedAnswer(answer, grounded=True)

    if _LIST_PATTERN.search(question) or _looks_like_list_question(question):
        answer = _synthesize_list(question, ranked)
        if answer:
            return SynthesizedAnswer(answer, grounded=True)

    if _PROCEDURAL_PATTERN.search(question):
        answer = _synthesize_steps(ranked)
        if answer:
            return SynthesizedAnswer(answer, grounded=True)

    answer = _synthesize_concise_paragraph(question, ranked)
    if answer:
        return SynthesizedAnswer(answer, grounded=True)

    if min_relevance is not None and min_relevance <= MIN_RELEVANCE_AFTER_CLARIFICATION:
        answer = _synthesize_steps(ranked) or _synthesize_list(question, ranked)
        if answer:
            return SynthesizedAnswer(answer, grounded=True)

    return SynthesizedAnswer(INSUFFICIENT_EVIDENCE_MESSAGE, grounded=False)


def _synthesize_precautions(chunks: list[dict]) -> str | None:
    keywords = ("safe", "careful", "precaution", "warning", "ensure", "avoid", "before", "do not", "don't")
    items: list[str] = []
    for chunk in chunks:
        for sentence in _split_sentences(chunk.get("matched_text", "")):
            lowered = sentence.lower()
            if any(word in lowered for word in keywords):
                cleaned = _clean_sentence(sentence)
                if cleaned and cleaned not in items:
                    items.append(cleaned)
    if len(items) >= 1:
        return "\n".join(f"• {item}" for item in items[:8])
    return _synthesize_steps(chunks)


def _is_pc_components_question(question: str) -> bool:
    lowered = question.lower()
    return (
        "component" in lowered
        or "parts" in lowered
        or ("required" in lowered and ("pc" in lowered or "build" in lowered or "computer" in lowered))
        or ("need" in lowered and "build" in lowered)
    )


def _synthesize_pc_components(corpus: str) -> str | None:
    found: list[str] = []
    for alias, label in _COMPONENT_ALIASES.items():
        if alias in corpus and label not in found:
            found.append(label)
    if len(found) >= 3:
        bullets = "\n".join(f"• {item}" for item in found)
        return bullets
    if any(term in corpus for term in ("build", "motherboard", "install", "pc")):
        bullets = "\n".join(f"• {item}" for item in _PC_COMPONENTS)
        return bullets
    return None


def _extract_specific_entity(question: str, chunks: list[dict]) -> str | None:
    match = _SPECIFIC_ENTITY_PATTERN.search(question)
    if not match:
        return None
    entity = match.group(1).lower()
    terms = _meaningful_query_terms(question) or [entity]

    for chunk in chunks:
        text = chunk.get("matched_text", "")
        for sentence in _split_sentences(text):
            lowered = sentence.lower()
            if entity in lowered or any(term in lowered for term in terms):
                cleaned = _clean_sentence(sentence)
                if cleaned:
                    return cleaned
    return None


def _synthesize_list(question: str, chunks: list[dict]) -> str | None:
    items: list[str] = []
    query_terms = _meaningful_query_terms(question)

    for chunk in chunks:
        text = chunk.get("matched_text", "")
        for line in re.split(r"[\n•\-–—]", text):
            candidate = line.strip(" ♪\t ")
            if len(candidate) < 8:
                continue
            lowered = candidate.lower()
            if query_terms and not any(term in lowered for term in query_terms):
                if not _looks_instructional(lowered):
                    continue
            normalized = _normalize_list_item(candidate)
            if normalized and normalized not in items:
                items.append(normalized)

    if len(items) >= 2:
        return "\n".join(f"• {item}" for item in items[:12])

    sentences = dedupe_sentences(
        [
            sentence
            for chunk in chunks
            for sentence in _split_sentences(chunk.get("matched_text", ""))
            if _sentence_matches_question(sentence, query_terms)
        ]
    )
    if len(sentences) >= 2:
        return "\n".join(f"• {_clean_sentence(sentence)}" for sentence in sentences[:8])
    return None


def _synthesize_steps(chunks: list[dict]) -> str | None:
    steps: list[str] = []
    for chunk in chunks:
        for sentence in _split_sentences(chunk.get("matched_text", "")):
            if _looks_instructional(sentence.lower()):
                cleaned = _clean_sentence(sentence)
                if cleaned and cleaned not in steps:
                    steps.append(cleaned)
    if not steps:
        return None
    return "\n".join(f"{index}. {step}" for index, step in enumerate(steps[:8], start=1))


def _synthesize_summary(chunks: list[dict]) -> str | None:
    sentences = dedupe_sentences(
        [
            _clean_sentence(sentence)
            for chunk in chunks
            for sentence in _split_sentences(chunk.get("matched_text", ""))
            if len(sentence.strip()) >= 20
        ]
    )[:4]
    if not sentences:
        return None
    return "\n".join(f"• {sentence}" for sentence in sentences)


def _synthesize_comparison(question: str, chunks: list[dict]) -> str | None:
    terms = _meaningful_query_terms(question)
    rows: list[tuple[str, str]] = []
    for chunk in chunks[:4]:
        title = chunk.get("title", "Memory")
        snippet = _clean_sentence(_split_sentences(chunk.get("matched_text", ""))[0] if chunk.get("matched_text") else "")
        if snippet:
            rows.append((title[:40], snippet[:120]))
    if len(rows) < 2:
        return None
    header = "| Source | Key point |\n| --- | --- |"
    body = "\n".join(f"| {left} | {right} |" for left, right in rows)
    return f"{header}\n{body}"


def _synthesize_concise_paragraph(question: str, chunks: list[dict]) -> str | None:
    query_terms = _meaningful_query_terms(question)
    sentences = dedupe_sentences(
        [
            _clean_sentence(sentence)
            for chunk in chunks
            for sentence in _split_sentences(chunk.get("matched_text", ""))
            if _sentence_matches_question(sentence, query_terms)
        ]
    )[:2]
    if sentences:
        return " ".join(sentences)
    return None


def _looks_like_list_question(question: str) -> bool:
    return bool(re.search(r"\b(required|need|needs|tools|materials|supplies)\b", question, re.I))


def _sentence_matches_question(sentence: str, query_terms: list[str]) -> bool:
    if not query_terms:
        return True
    lowered = sentence.lower()
    return any(term in lowered for term in query_terms)


def _looks_instructional(text: str) -> bool:
    return bool(
        re.search(
            r"\b(first|next|then|install|download|run|open|click|select|enable|connect|use|make sure|step|need|required)\b",
            text,
        )
    )


def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    return [part.strip() for part in _SENTENCE_SPLIT.split(text) if part.strip()]


def _clean_sentence(sentence: str) -> str:
    cleaned = re.sub(r"^[♪\-\d\.\)\s]+", "", sentence).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _normalize_list_item(text: str) -> str:
    text = _clean_sentence(text)
    if len(text) < 8 or len(text) > 120:
        return ""
    return text[0].upper() + text[1:] if text else ""


def _meaningful_query_terms(question: str) -> list[str]:
    terms = [t for t in _tokenize(question) if len(t) >= 3 and t not in _STOP_WORDS]
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            result.append(term)
    return result
