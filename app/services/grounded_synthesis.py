"""Grounded answer synthesis with optional LLM and deterministic fallback."""

from __future__ import annotations

import time

from app.config import Settings, get_settings
from app.models.capsule import StructuredAnswer
from app.services.answer_generator import GeneratedAnswer
from app.services.answer_synthesizer import synthesize_answer
from app.services.llm_provider import get_llm_provider


def synthesize_grounded_answer(
    question: str,
    chunks: list[dict],
    *,
    answer_format: str = "concise",
    min_relevance: float | None = None,
    settings: Settings | None = None,
    user_id: str | None = None,
) -> tuple[GeneratedAnswer, str | None, float]:
    """Produce a grounded answer from evidence.

    Optional LLM output is accepted only when its grounding contract passes. If
    the provider fails, returns malformed content, cites unknown evidence, or
    otherwise fails validation, the deterministic synthesizer remains the
    authoritative fallback.

    Returns (GeneratedAnswer, confidence, synthesis_ms).
    """
    settings = settings or get_settings()
    t0 = time.perf_counter()

    for chunk in chunks:
        chunk.setdefault("evidence_id", _evidence_id(chunk))

    provider = get_llm_provider(settings, user_id=user_id)
    if provider is not None:
        try:
            structured = provider.synthesize(
                question=question,
                evidence=chunks,
                answer_format=answer_format,
            )
            if (
                structured
                and structured.answer_markdown.strip()
                and _validate_grounding(structured, chunks)
            ):
                elapsed = (time.perf_counter() - t0) * 1000
                return (
                    GeneratedAnswer(answer=structured.answer_markdown, grounded=True),
                    structured.confidence,
                    elapsed,
                )
        except Exception:
            # Optional AI must never take down or weaken the deterministic path.
            pass

    synthesized = synthesize_answer(question, chunks, min_relevance=min_relevance)
    confidence = "high" if synthesized.grounded else "low"
    elapsed = (time.perf_counter() - t0) * 1000
    return (
        GeneratedAnswer(answer=synthesized.answer, grounded=synthesized.grounded),
        confidence,
        elapsed,
    )


def _evidence_id(chunk: dict) -> str:
    video_id = chunk.get("video_id") or "unknown"
    start = chunk.get("start_time")
    if start is not None:
        return f"{video_id}@{int(start)}"
    return str(chunk.get("doc_id") or video_id)


def _validate_grounding(structured: StructuredAnswer, chunks: list[dict]) -> bool:
    """Validate that an LLM answer is tied to evidence actually supplied.

    The model must cite at least one known evidence ID. Unknown/fabricated IDs,
    low confidence, empty evidence, or empty answers fail closed to deterministic
    synthesis. Lexical overlap is a lightweight additional guard; valid cited
    evidence plus high confidence may contain paraphrases with little overlap.
    """
    if not structured.answer_markdown.strip() or structured.confidence == "low":
        return False
    if not chunks or not structured.evidence_ids:
        return False

    allowed_ids = {
        str(chunk.get("evidence_id") or _evidence_id(chunk))
        for chunk in chunks
    }
    cited_ids = {str(item) for item in structured.evidence_ids if str(item).strip()}
    if not cited_ids or not cited_ids.issubset(allowed_ids):
        return False

    corpus = " ".join(chunk.get("matched_text", "") for chunk in chunks).lower()
    if not corpus.strip():
        return False

    tokens = [t for t in structured.answer_markdown.lower().split() if len(t) >= 5]
    if not tokens:
        return structured.confidence in {"high", "medium"}
    overlap = sum(1 for token in tokens[:20] if token in corpus)
    return overlap >= 1 or structured.confidence == "high"
