"""Memory Capsule generation — deterministic fallback with optional LLM."""

from __future__ import annotations

import json
import re
from typing import Any

from app.models.capsule import MemoryCapsule, MemorySection
from app.models.reflection import ReflectionInput
from app.models.video import VideoMetadata
from app.models.transcript import TranscriptResult
from app.services.enrichment_service import _top_keywords, enrich_video


def build_capsule_deterministic(
    *,
    metadata: VideoMetadata,
    transcript: TranscriptResult,
    reflection: ReflectionInput | None = None,
    enrichment=None,
) -> MemoryCapsule:
    enrichment = enrichment or enrich_video(
        title=metadata.title,
        description=metadata.description,
        channel=metadata.channel,
        transcript_text=transcript.full_text,
        chunk_texts=[seg.text for seg in transcript.segments[:20]],
    )
    keywords = _top_keywords(
        f"{metadata.title} {metadata.description} {transcript.full_text[:4000]}", limit=12
    )
    components = _extract_components(transcript.full_text)
    procedures = _extract_procedures(transcript.full_text)
    sections = _build_sections(transcript)

    difficulty = reflection.difficulty.value if reflection else "unknown"
    styles: list[str] = []
    if reflection:
        styles.append(reflection.preferred_style.value.replace("_", " "))

    return MemoryCapsule(
        video_id=metadata.video_id,
        title=metadata.title,
        one_line_memory=enrichment.one_line_memory,
        short_summary=_short_summary(transcript.full_text),
        topics=keywords[:8],
        entities=_extract_entities(metadata, transcript.full_text),
        tools_or_components=components,
        procedures=procedures,
        claims=_extract_claims(transcript.full_text),
        difficulty=difficulty,
        content_style=styles or ["practical"],
        creator=metadata.channel,
        duration=float(metadata.duration or 0),
        upload_date="",
        save_reason=reflection.save_reason.value if reflection else "",
        user_goal=reflection.goal if reflection else "",
        sections=sections,
    )


def build_capsule_with_optional_llm(
    *,
    metadata: VideoMetadata,
    transcript: TranscriptResult,
    reflection: ReflectionInput | None = None,
) -> MemoryCapsule:
    fallback = build_capsule_deterministic(
        metadata=metadata, transcript=transcript, reflection=reflection
    )
    try:
        from app.services.llm_provider import get_llm_provider

        provider = get_llm_provider()
        if provider is None:
            return fallback
        raw = provider.generate_capsule_json(
            title=metadata.title,
            description=metadata.description,
            transcript_excerpt=transcript.full_text[:6000],
            reflection_goal=reflection.goal if reflection else "",
        )
        if not raw:
            return fallback
        return _parse_capsule_json(raw, fallback)
    except Exception:
        return fallback


def _parse_capsule_json(raw: str, fallback: MemoryCapsule) -> MemoryCapsule:
    try:
        data = json.loads(raw)
        capsule = MemoryCapsule.model_validate(data)
        if not capsule.video_id:
            capsule = capsule.model_copy(update={"video_id": fallback.video_id})
        return capsule
    except Exception:
        # repair attempt: extract JSON object
        match = re.search(r"\{.*\}", raw, re.S)
        if match:
            try:
                data = json.loads(match.group(0))
                capsule = MemoryCapsule.model_validate(data)
                return capsule.model_copy(update={"video_id": fallback.video_id})
            except Exception:
                pass
    return fallback


def _short_summary(text: str, max_len: int = 280) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 3].rsplit(" ", 1)[0] + "..."


def _extract_components(text: str) -> list[str]:
    aliases = [
        "cpu", "motherboard", "ram", "ssd", "hdd", "power supply", "psu",
        "graphics card", "gpu", "cooler", "case fan", "case",
    ]
    lowered = text.lower()
    found = []
    for alias in aliases:
        if alias in lowered:
            label = alias.upper() if len(alias) <= 4 else alias.title()
            if label not in found:
                found.append(label)
    return found[:12]


def _extract_procedures(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out = []
    for sentence in sentences:
        if re.search(r"\b(first|next|then|step|install|connect|make sure)\b", sentence, re.I):
            cleaned = sentence.strip()
            if 20 <= len(cleaned) <= 160 and cleaned not in out:
                out.append(cleaned)
    return out[:8]


def _extract_claims(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out = []
    for sentence in sentences:
        if re.search(r"\b(is|are|means|should|must|important)\b", sentence, re.I):
            cleaned = sentence.strip()
            if 25 <= len(cleaned) <= 140 and cleaned not in out:
                out.append(cleaned)
    return out[:6]


def _extract_entities(metadata: VideoMetadata, text: str) -> list[str]:
    entities = [metadata.channel, metadata.title.split("-")[0].strip()]
    for word in re.findall(r"\b[A-Z][A-Za-z0-9\-]{2,}\b", text[:2000]):
        if word not in entities:
            entities.append(word)
    return entities[:10]


def _build_sections(transcript: TranscriptResult) -> list[MemorySection]:
    if not transcript.segments:
        return []
    sections: list[MemorySection] = []
    bucket_size = max(1, len(transcript.segments) // 4)
    for i in range(0, len(transcript.segments), bucket_size):
        chunk = transcript.segments[i : i + bucket_size]
        if not chunk:
            continue
        text = " ".join(seg.text for seg in chunk)
        sections.append(
            MemorySection(
                title=f"Section {len(sections) + 1}",
                summary=_short_summary(text, 160),
                start_time=chunk[0].start_time_sec,
                end_time=chunk[-1].start_time_sec + chunk[-1].duration_sec,
                keywords=_top_keywords(text, limit=5),
            )
        )
    return sections[:8]
