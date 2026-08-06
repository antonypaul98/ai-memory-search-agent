"""
Grounded answer generation from retrieved memory chunks.

DeterministicAnswerGenerator is the default. Replace with an LLM-backed
implementation by subclassing AnswerGenerator without changing ChatService.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.services.answer_synthesizer import synthesize_answer
from app.services.enrichment_service import _STOP_WORDS, _tokenize

INSUFFICIENT_EVIDENCE_MESSAGE = (
    "I could not find enough information in your saved memories to answer confidently."
)

MIN_RELEVANCE_SCORE = 0.25
MAX_BULLET_SENTENCES = 5
MAX_PARAGRAPH_SENTENCES = 3
MIN_SENTENCE_LENGTH = 25

_PROCEDURAL_PATTERN = re.compile(
    r"\b(how\s+do|how\s+to|install|setup|set\s+up|configure|steps?|step-by-step|guide|tutorial)\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class GeneratedAnswer:
    """Result from an answer generator."""

    answer: str
    grounded: bool


class AnswerGenerator(ABC):
    """Interface for grounded answer generation (deterministic or LLM)."""

    @abstractmethod
    def generate(
        self,
        question: str,
        chunks: list[dict],
        *,
        min_relevance: float | None = None,
    ) -> GeneratedAnswer:
        """Build an answer strictly from retrieved chunk text."""


class DeterministicAnswerGenerator(AnswerGenerator):
    """Synthesize concise grounded answers from retrieved transcript chunks."""

    def generate(
        self,
        question: str,
        chunks: list[dict],
        *,
        min_relevance: float | None = None,
    ) -> GeneratedAnswer:
        synthesized = synthesize_answer(question, chunks, min_relevance=min_relevance)
        return GeneratedAnswer(answer=synthesized.answer, grounded=synthesized.grounded)


def dedupe_sentences(sentences: list[str]) -> list[str]:
    """Remove duplicate or near-duplicate sentences."""
    unique: list[str] = []
    seen: set[str] = set()

    for sentence in sentences:
        normalized = _normalize_sentence(sentence)
        if len(normalized) < MIN_SENTENCE_LENGTH:
            continue
        if normalized in seen:
            continue
        if any(normalized in existing or existing in normalized for existing in seen):
            continue
        seen.add(normalized)
        unique.append(sentence.strip())

    return unique


def _select_sentences(question: str, chunks: list[dict]) -> list[str]:
    query_terms = _meaningful_query_terms(question)
    procedural = _is_procedural_question(question)
    limit = MAX_BULLET_SENTENCES if procedural else MAX_PARAGRAPH_SENTENCES

    scored: list[tuple[float, str]] = []
    for chunk in chunks:
        chunk_weight = chunk["relevance_score"]
        for sentence in _split_sentences(chunk.get("matched_text", "")):
            if len(sentence.strip()) < MIN_SENTENCE_LENGTH:
                continue
            overlap = sum(1 for term in query_terms if term in sentence.lower())
            if query_terms and overlap == 0 and not _looks_instructional(sentence):
                continue
            score = overlap * 2 + chunk_weight + (0.5 if _looks_instructional(sentence) else 0.0)
            scored.append((score, sentence.strip()))

    scored.sort(key=lambda item: item[0], reverse=True)
    candidates = [sentence for _score, sentence in scored]
    return dedupe_sentences(candidates)[:limit]


def _is_procedural_question(question: str) -> bool:
    return bool(_PROCEDURAL_PATTERN.search(question))


def _looks_instructional(sentence: str) -> bool:
    lowered = sentence.lower()
    return bool(
        re.search(
            r"\b(first|next|then|install|download|run|open|click|select|enable|connect|use|make sure|step)\b",
            lowered,
        )
    )


def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    return [part.strip() for part in _SENTENCE_SPLIT.split(text) if part.strip()]


def _normalize_sentence(sentence: str) -> str:
    return re.sub(r"[^a-z0-9\s]", "", sentence.lower()).strip()


def _meaningful_query_terms(question: str) -> list[str]:
    terms = [t for t in _tokenize(question) if len(t) >= 3 and t not in _STOP_WORDS]
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            result.append(term)
    return result
