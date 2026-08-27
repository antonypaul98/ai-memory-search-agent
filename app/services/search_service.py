"""
Semantic search: embed query → search Chroma → roll up results by video.
Supports optional YouTube Memory filters without breaking the existing API.
"""

from __future__ import annotations

import time

from app.config import Settings, get_settings
from app.db.repositories.memory_repository import MemoryRepository
from app.db.video_registry import VideoRegistry, get_video_registry
from app.db.youtube_memory_store import YouTubeMemoryStore
from app.models.metrics import SearchMetrics
from app.models.user import LOCAL_DEFAULT_USER_ID
from app.models.video import SearchFilters, SearchResponse, SearchResultItem
from app.services.ahme_engine import AdaptiveHierarchicalMemoryEngine
from app.services.enrichment_service import build_why_matched
from app.utils.youtube_urls import build_original_url, build_timestamp_url


class SearchService:
    """Search ingested memories by natural-language query."""

    def __init__(
        self,
        settings: Settings | None = None,
        repository: MemoryRepository | None = None,
        registry: VideoRegistry | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._repository = repository or MemoryRepository(self._settings)
        self._registry = registry or get_video_registry(self._settings)
        self._yt_store = YouTubeMemoryStore(self._settings)
        self._ahme = AdaptiveHierarchicalMemoryEngine(
            settings=self._settings,
            repository=self._repository,
        )

    def search(
        self,
        query: str,
        limit: int = 5,
        *,
        debug: bool = False,
        user_id: str | None = None,
        filters: SearchFilters | None = None,
    ) -> SearchResponse:
        """Run semantic / hybrid search via AHME with optional metadata filters."""
        started = time.perf_counter()
        owner = user_id or LOCAL_DEFAULT_USER_ID
        if user_id:
            try:
                from app.services.agent_status_service import AgentStatusService

                AgentStatusService(self._settings).record_search(user_id=user_id, query=query)
            except Exception:
                pass

        chunk_hits, metrics = self._ahme.retrieve(
            query, top_k=self._settings.search_top_k_chunks, user_id=owner
        )

        if chunk_hits:
            self._registry.record_search(
                [hit["video_id"] for hit in chunk_hits if hit.get("video_id")],
                user_id=owner,
            )

        grouped = _group_by_video(chunk_hits)
        ranked = sorted(
            grouped.values(),
            key=lambda hit: hit["relevance_score"],
            reverse=True,
        )

        results: list[SearchResultItem] = []
        for hit in ranked:
            item = _to_search_result_item(
                hit=hit,
                query=query,
                registry=self._registry,
                yt_store=self._yt_store,
                user_id=owner,
            )
            if filters and not _passes_filters(item, filters):
                continue
            results.append(item)
            if len(results) >= limit:
                break

        latency = round((time.perf_counter() - started) * 1000, 1)
        try:
            self._yt_store.record_search_latency(latency)
        except Exception:
            pass

        applied = filters.model_dump(exclude_none=True) if filters else {}
        response = SearchResponse(query=query, results=results, filters_applied=applied)
        if debug and self._settings.debug:
            response.debug_metrics = metrics
        return response


def _group_by_video(hits: list[dict]) -> dict[str, dict]:
    """Keep the highest-scoring chunk per video."""
    best_by_video: dict[str, dict] = {}
    for hit in hits:
        video_id = hit.get("video_id") or ""
        if not video_id:
            continue
        existing = best_by_video.get(video_id)
        if existing is None or hit["relevance_score"] > existing["relevance_score"]:
            best_by_video[video_id] = hit
    return best_by_video


def _to_search_result_item(
    *,
    hit: dict,
    query: str,
    registry: VideoRegistry,
    yt_store: YouTubeMemoryStore,
    user_id: str | None,
) -> SearchResultItem:
    original_url = build_original_url(hit.get("url", ""))
    start_time = hit.get("start_time")
    relevance = round(hit["relevance_score"], 4)
    description = hit.get("description", "")
    video_id = hit["video_id"]
    owner = user_id or LOCAL_DEFAULT_USER_ID

    reflection = registry.get_reflection(video_id, user_id=owner)
    usage = registry.get_usage(video_id, user_id=owner)
    if reflection.goal and query:
        reflection.reflection_message = (
            f"You originally saved this to {reflection.goal.lower().strip()}. "
            f"Your current search still aligns with that goal."
            if reflection.goal.lower() in query.lower()
            else reflection.reflection_message
        )

    ai_summary = hit.get("one_line_memory") or _short_summary(hit.get("matched_text", ""))
    why = build_why_matched(
        query=query,
        matched_text=hit["matched_text"],
        title=hit["title"],
        description=description,
        relevance_score=relevance,
        start_time=start_time,
    )
    matching_metadata: list[str] = []
    q_lower = query.lower()
    if hit.get("title") and any(tok in hit["title"].lower() for tok in q_lower.split() if len(tok) > 2):
        matching_metadata.append("title")
    if description and any(tok in description.lower() for tok in q_lower.split() if len(tok) > 2):
        matching_metadata.append("description")
    if hit.get("channel") and hit["channel"].lower() in q_lower:
        matching_metadata.append("channel")
    if hit.get("matched_text"):
        matching_metadata.append("transcript")

    yt = yt_store.get(video_id, user_id=owner)
    tags = hit.get("tags") or (yt.tags if yt else [])
    if isinstance(tags, str):
        tags = [t for t in tags.split(",") if t]
    for tag in tags:
        if tag and tag.lower() in q_lower:
            matching_metadata.append(f"tag:{tag}")

    source_type = hit.get("source_type") or "youtube"
    connector_id = hit.get("connector_id") or "youtube.v1"
    page_number = hit.get("page_number") or None
    if page_number == 0:
        page_number = None
    citation = ""
    if source_type == "pdf" and page_number:
        citation = f"{hit.get('title', 'PDF')} p.{page_number}"
    elif source_type == "github":
        citation = hit.get("url") or original_url
    else:
        citation = original_url

    return SearchResultItem(
        video_id=video_id,
        title=hit["title"],
        channel=hit["channel"],
        thumbnail=hit["thumbnail"],
        url=original_url,
        original_url=original_url,
        timestamp_url=build_timestamp_url(original_url, start_time),
        duration=hit.get("duration") if hit.get("duration") != -1 else (yt.duration_sec if yt else None),
        matched_text=hit["matched_text"],
        start_time=start_time,
        end_time=hit.get("end_time"),
        relevance_score=relevance,
        similarity_score=relevance,
        confidence=min(1.0, max(0.0, relevance)),
        why_matched=why,
        matching_metadata=matching_metadata,
        one_line_memory=hit.get("one_line_memory", ""),
        ai_summary=ai_summary,
        why_saved=hit.get("why_saved") or [],
        action_items=hit.get("action_items") or [],
        save_reason=reflection.save_reason,
        current_goal=reflection.goal,
        reflection=reflection,
        usage=usage,
        is_duplicate=bool(yt.is_duplicate) if yt else False,
        processing_complete=(
            yt.processing_status.value in {"completed", "indexed"} if yt else True
        ),
        transcript_available=bool(hit.get("transcript_available", True)),
        language=hit.get("language") or (yt.language if yt else None),
        channel_id=hit.get("channel_id") or (yt.channel_id if yt else ""),
        published_at=hit.get("published_at") or (yt.published_at if yt else None),
        source_type=str(source_type),
        connector_id=str(connector_id),
        page_number=int(page_number) if page_number else None,
        citation_ref=citation,
        import_date=hit.get("created_at") or (yt.saved_at if yt else None),
        related_memories=list(hit.get("related_video_ids") or []),
    )


def _passes_filters(item: SearchResultItem, filters: SearchFilters) -> bool:
    if filters.channel and filters.channel.lower() not in item.channel.lower():
        return False
    if filters.language and (item.language or "").lower() != filters.language.lower():
        return False
    if filters.transcript_available is not None and item.transcript_available != filters.transcript_available:
        return False
    if filters.duration_min is not None and (item.duration or 0) < filters.duration_min:
        return False
    if filters.duration_max is not None and (item.duration or 0) > filters.duration_max:
        return False
    if filters.min_confidence is not None and (item.confidence or 0) < filters.min_confidence:
        return False
    item_day = _filter_day(item.published_at) or _filter_day(getattr(item, "import_date", None))
    if filters.date_from or filters.date_to:
        if not item_day:
            return False
        from_day = _filter_day(filters.date_from)
        to_day = _filter_day(filters.date_to)
        if from_day and item_day < from_day:
            return False
        if to_day and item_day > to_day:
            return False
    if filters.tags:
        hay = " ".join(item.matching_metadata).lower()
        if not any(t.lower() in hay or t.lower() in item.title.lower() for t in filters.tags):
            return False
    return True


def _filter_day(value: str | None) -> str | None:
    """Normalize filter/publish timestamps to YYYY-MM-DD for inclusive day comparisons."""
    if not value:
        return None
    text = str(value).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return text or None


def _short_summary(text: str, max_len: int = 140) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 3].rstrip() + "..."
