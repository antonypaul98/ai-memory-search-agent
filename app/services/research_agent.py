"""Read-only, deterministic Research Agent over the user's saved memory.

The agent deliberately performs no external fetches and no memory writes. It runs
bounded follow-up retrievals, deduplicates sources, and emits a report whose source
markers map directly to retrieved memory citations.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from app.models.research_agent import (
    ResearchAgentRequest,
    ResearchAgentResponse,
    ResearchSource,
)
from app.services.search_service import SearchService


class ResearchAgent:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._search = SearchService(self._settings)

    def run(self, *, user_id: str, request: ResearchAgentRequest) -> ResearchAgentResponse:
        owner = (user_id or "").strip()
        if not owner:
            raise ValueError("user_id is required")

        question = request.question.strip()
        queries: list[str] = []
        collected: dict[str, ResearchSource] = {}
        seed_title = ""

        for hop in range(1, request.depth + 1):
            query = question if hop == 1 or not seed_title else f"{question} {seed_title}"
            queries.append(query)
            response = self._search.search(
                query,
                limit=request.max_sources,
                user_id=owner,
            )
            rows = response.model_dump(mode="json").get("results", [])
            if not isinstance(rows, list):
                rows = []

            for raw in rows:
                if not isinstance(raw, dict):
                    continue
                key = self._source_key(raw)
                if not key or key in collected:
                    continue
                collected[key] = ResearchSource(
                    source_id=key,
                    title=str(raw.get("title") or "Untitled memory"),
                    citation_ref=str(
                        raw.get("citation_ref")
                        or raw.get("timestamp_url")
                        or raw.get("original_url")
                        or raw.get("url")
                        or ""
                    ),
                    matched_text=self._clean_excerpt(raw.get("matched_text")),
                    relevance_score=float(raw.get("relevance_score") or 0.0),
                    hop=hop,
                )
                if len(collected) >= request.max_sources:
                    break

            if rows:
                first = rows[0] if isinstance(rows[0], dict) else {}
                seed_title = str(first.get("title") or "").strip()
            if len(collected) >= request.max_sources:
                break

        sources = list(collected.values())[: request.max_sources]
        report = self._build_report(question, sources)
        return ResearchAgentResponse(
            question=question,
            depth=request.depth,
            queries=queries,
            report=report,
            sources=sources,
            grounded=True,
        )

    @staticmethod
    def _source_key(raw: dict[str, Any]) -> str:
        source_type = str(raw.get("source_type") or "memory")
        external_id = str(raw.get("video_id") or raw.get("citation_ref") or raw.get("url") or "")
        external_id = external_id.strip()
        return f"{source_type}:{external_id}" if external_id else ""

    @staticmethod
    def _clean_excerpt(value: Any, max_len: int = 500) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= max_len:
            return text
        return text[: max_len - 3].rstrip() + "..."

    @staticmethod
    def _build_report(question: str, sources: list[ResearchSource]) -> str:
        if not sources:
            return (
                f"I could not find evidence in your saved memory for: {question}. "
                "No external sources were used."
            )

        lines = [f"Research summary for: {question}", ""]
        for index, source in enumerate(sources, start=1):
            excerpt = source.matched_text or "Retrieved as a relevant saved memory."
            lines.append(f"[S{index}] {source.title} — {excerpt}")
        lines.extend(["", "Sources:"])
        for index, source in enumerate(sources, start=1):
            citation = source.citation_ref or "saved-memory citation unavailable"
            lines.append(f"[S{index}] {citation}")
        return "\n".join(lines)
