"""
Chat with saved memories: retrieve chunks → clarify → synthesize answer → cite sources.
"""

from app.config import Settings, get_settings
from app.db.repositories.memory_repository import MemoryRepository
from app.db.video_registry import VideoRegistry, get_video_registry
from app.middleware.observability import record_chat_outcome
from app.models.chat import ChatResponse, ChatSource, ClarificationOption
from app.services.ahme_engine import AdaptiveHierarchicalMemoryEngine
from app.services.clarification_service import analyze_clarification, filter_chunks_by_choice
from app.services.grounded_synthesis import synthesize_grounded_answer
from app.services.query_router import route_query
from app.services.recommendation_service import RecommendationService
from app.utils.youtube_urls import build_original_url, build_timestamp_url

_TIMESTAMP_BUCKET_SECONDS = 30


class ChatService:
    """Answer questions using retrieved transcript chunks only."""

    def __init__(
        self,
        settings: Settings | None = None,
        repository: MemoryRepository | None = None,
        registry: VideoRegistry | None = None,
        recommendation_service: RecommendationService | None = None,
        ahme: AdaptiveHierarchicalMemoryEngine | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._repository = repository or MemoryRepository(self._settings)
        self._registry = registry or get_video_registry(self._settings)
        self._recommendations = recommendation_service or RecommendationService(
            settings=self._settings,
            repository=self._repository,
            registry=self._registry,
        )
        self._ahme = ahme or AdaptiveHierarchicalMemoryEngine(
            settings=self._settings,
            repository=self._repository,
        )

    def chat(
        self,
        question: str,
        top_k: int = 6,
        clarification_choice: str | None = None,
        *,
        debug: bool = False,
        user_id: str | None = None,
    ) -> ChatResponse:
        """Retrieve relevant chunks and produce a synthesized grounded answer."""
        route = route_query(question, settings=self._settings)
        chunk_hits, metrics = self._ahme.retrieve(
            question,
            top_k=top_k,
            user_id=user_id,
        )

        if chunk_hits:
            self._registry.record_search([hit["video_id"] for hit in chunk_hits if hit.get("video_id")])

        if not clarification_choice:
            clarification = analyze_clarification(question, chunk_hits)
            if clarification.needs_clarification and clarification.options:
                response = ChatResponse(
                    answer="",
                    sources=[],
                    grounded=False,
                    needs_clarification=True,
                    clarification_prompt=clarification.prompt,
                    clarification_options=[
                        ClarificationOption(id=opt.id, label=opt.label)
                        for opt in clarification.options
                    ],
                )
                if debug and self._settings.debug:
                    response.debug_metrics = metrics
                record_chat_outcome(grounded=False, needs_clarification=True)
                return response

        if clarification_choice:
            chunk_hits = filter_chunks_by_choice(chunk_hits, clarification_choice)

        deduped_sources = _dedupe_sources(chunk_hits)
        generated, confidence, synthesis_ms = synthesize_grounded_answer(
            question,
            chunk_hits,
            answer_format=route.answer_format,
            min_relevance=0.0 if clarification_choice else None,
            settings=self._settings,
        )
        metrics.synthesis_ms = synthesis_ms
        metrics.estimated_llm_tokens = max(1, len(generated.answer.split()) * 2)

        top_video_ids = {hit.get("video_id") for hit in deduped_sources if hit.get("video_id")}
        recommendations = self._recommendations.recommend_for_query(
            question,
            exclude_video_ids=top_video_ids,
        )

        response = ChatResponse(
            answer=generated.answer,
            sources=[_to_chat_source(hit) for hit in deduped_sources],
            grounded=generated.grounded,
            recommendations=recommendations,
            confidence=confidence,
        )
        if debug and self._settings.debug:
            response.debug_metrics = metrics
        record_chat_outcome(grounded=response.grounded, needs_clarification=False)
        return response


def _dedupe_sources(chunks: list[dict]) -> list[dict]:
    """Avoid duplicate citations from the same video and timestamp range."""
    best_by_slot: dict[tuple[str, int], dict] = {}

    for chunk in sorted(chunks, key=lambda c: c["relevance_score"], reverse=True):
        video_id = chunk.get("video_id") or ""
        if not video_id:
            continue
        start = chunk.get("start_time")
        bucket = int(start // _TIMESTAMP_BUCKET_SECONDS) if start is not None else -1
        slot = (video_id, bucket)
        existing = best_by_slot.get(slot)
        if existing is None or chunk["relevance_score"] > existing["relevance_score"]:
            best_by_slot[slot] = chunk

    return sorted(
        best_by_slot.values(),
        key=lambda c: c["relevance_score"],
        reverse=True,
    )


def _to_chat_source(hit: dict) -> ChatSource:
    original_url = build_original_url(hit.get("url", ""))
    start_time = hit.get("start_time")
    return ChatSource(
        video_id=hit["video_id"],
        title=hit.get("title", ""),
        url=original_url,
        start_time=start_time,
        end_time=hit.get("end_time"),
        matched_text=hit.get("matched_text", ""),
        relevance_score=round(hit["relevance_score"], 4),
        timestamp_url=build_timestamp_url(original_url, start_time),
    )
