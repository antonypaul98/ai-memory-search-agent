"""
Deterministic video enrichment from title, description, and transcript.

No external APIs — extractive logic only. Does not invent facts.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

# Common stop words for keyword extraction.
_STOP_WORDS = frozenset(
    """
    a an the and or but in on at to for of is are was were be been being
    it this that these those i you we they he she my your our their with
    from as by about into through during before after above below up down
    out over under again further then once here there when where why how
    all each few more most other some such no nor not only own same so than
    too very can will just don should now ve ll re d s t m o
    """.split()
)

# Sentence-ending punctuation for splitting transcript text.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# Patterns suggesting actionable advice in transcript sentences.
_ACTION_PATTERNS = (
    re.compile(r"^\d+[\).\]]\s+\S", re.IGNORECASE),
    re.compile(r"^(try|make|start|use|add|avoid|remember|consider|focus on|don't|do not)\b", re.IGNORECASE),
    re.compile(r"\b(you should|you need to|make sure|be sure to|step \d+)\b", re.IGNORECASE),
)

# Minimum length for a sentence to be considered an action item.
_MIN_ACTION_LEN = 20


@dataclass(frozen=True)
class EnrichmentResult:
    """Extracted enrichment fields stored at ingest time."""

    one_line_memory: str
    why_saved: list[str]
    action_items: list[str]


def enrich_video(
    *,
    title: str,
    description: str,
    channel: str,
    transcript_text: str,
    chunk_texts: list[str],
) -> EnrichmentResult:
    """
    Build enrichment fields from stored video content.

    All output is derived from the provided title, description, channel,
    and transcript — nothing is fabricated.
    """
    one_line = _build_one_line_memory(title, description, chunk_texts, transcript_text)
    why_saved = _build_why_saved(title, description, channel, transcript_text)
    action_items = _extract_action_items(transcript_text)
    return EnrichmentResult(
        one_line_memory=one_line,
        why_saved=why_saved,
        action_items=action_items,
    )


def serialize_string_list(values: list[str]) -> str:
    """Store a string list in Chroma-compatible metadata."""
    return json.dumps(values)


def deserialize_string_list(raw: str | None) -> list[str]:
    """Load a string list from Chroma metadata."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item]


def build_why_matched(
    *,
    query: str,
    matched_text: str,
    title: str,
    description: str,
    relevance_score: float,
    start_time: float | None = None,
) -> str:
    """
    Explain why a search result matched, grounded in stored content.
    """
    parts: list[str] = []

    snippet = matched_text.strip()
    if len(snippet) > 160:
        snippet = snippet[:157] + "..."
    if snippet:
        time_note = ""
        if start_time is not None:
            time_note = f" (at {int(start_time)}s)"
        parts.append(f'Transcript passage matched{time_note}: "{snippet}"')

    query_terms = _meaningful_terms(query)
    if query_terms:
        title_lower = title.lower()
        title_hits = sorted({term for term in query_terms if term in title_lower})
        if title_hits:
            parts.append(f"Title also contains: {', '.join(title_hits)}.")

        if description:
            desc_lower = description.lower()
            desc_hits = sorted({term for term in query_terms if term in desc_lower})
            if desc_hits:
                parts.append(f"Description also mentions: {', '.join(desc_hits)}.")

    parts.append(f"Relevance score: {relevance_score:.2f}.")
    return " ".join(parts)


def _build_one_line_memory(
    title: str,
    description: str,
    chunk_texts: list[str],
    transcript_text: str,
) -> str:
    title = title.strip() or "Untitled video"
    desc_sentence = _first_sentence(description)
    if desc_sentence and len(desc_sentence) >= 20:
        summary = desc_sentence
    elif chunk_texts:
        summary = _first_sentence(chunk_texts[0]) or chunk_texts[0][:120].strip()
    elif transcript_text.strip():
        summary = _first_sentence(transcript_text) or transcript_text[:120].strip()
    else:
        summary = "No transcript summary available."

    if len(summary) > 140:
        summary = summary[:137].rstrip() + "..."
    return f"{title} — {summary}"


def _build_why_saved(
    title: str,
    description: str,
    channel: str,
    transcript_text: str,
) -> list[str]:
    reasons: list[str] = []

    if channel.strip():
        reasons.append(
            f"You saved content from {channel.strip()}, which may reflect interest in this creator's topics."
        )

    title_terms = _top_keywords(f"{title} {description}", limit=3)
    if title_terms:
        reasons.append(
            f"The title and description center on: {', '.join(title_terms)}."
        )

    transcript_terms = _top_keywords(transcript_text, limit=3)
    if transcript_terms and transcript_terms != title_terms:
        reasons.append(
            f"The transcript repeatedly discusses: {', '.join(transcript_terms)}."
        )
    elif transcript_terms and not title_terms:
        reasons.append(
            f"The transcript focuses on: {', '.join(transcript_terms)}."
        )

    return reasons[:3]


def _extract_action_items(transcript_text: str) -> list[str]:
    if not transcript_text.strip():
        return []

    items: list[str] = []
    seen: set[str] = set()

    for sentence in _split_sentences(transcript_text):
        cleaned = sentence.strip()
        if len(cleaned) < _MIN_ACTION_LEN:
            continue
        if not _looks_actionable(cleaned):
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(cleaned if len(cleaned) <= 160 else cleaned[:157].rstrip() + "...")
        if len(items) >= 5:
            break

    return items


def _looks_actionable(sentence: str) -> bool:
    return any(pattern.search(sentence) for pattern in _ACTION_PATTERNS)


def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    return [part.strip() for part in _SENTENCE_SPLIT.split(text) if part.strip()]


def _first_sentence(text: str) -> str:
    sentences = _split_sentences(text.strip())
    return sentences[0] if sentences else ""


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _meaningful_terms(text: str) -> list[str]:
    terms = [t for t in _tokenize(text) if len(t) >= 3 and t not in _STOP_WORDS]
    # Preserve order, dedupe.
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            result.append(term)
    return result


def _top_keywords(text: str, limit: int = 3) -> list[str]:
    counts: dict[str, int] = {}
    for term in _tokenize(text):
        if len(term) < 4 or term in _STOP_WORDS:
            continue
        counts[term] = counts.get(term, 0) + 1

    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [word for word, _count in ranked[:limit]]
