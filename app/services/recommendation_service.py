"""Preference-aware recommendations from saved memories."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.core.embeddings import embed_query
from app.db.repositories.memory_repository import MemoryRepository
from app.db.video_registry import VideoRegistry, get_video_registry
from app.models.reflection import RecommendationItem


class RecommendationService:
    """Recommend saved memories aligned with user preferences."""

    def __init__(
        self,
        settings: Settings | None = None,
        repository: MemoryRepository | None = None,
        registry: VideoRegistry | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._repository = repository or MemoryRepository(self._settings)
        self._registry = registry or get_video_registry(self._settings)

    def recommend_for_query(
        self,
        query: str,
        *,
        limit: int = 3,
        exclude_video_ids: set[str] | None = None,
    ) -> list[RecommendationItem]:
        exclude = exclude_video_ids or set()
        query_embedding = embed_query(query, settings=self._settings)
        hits = self._repository.search(
            query_embedding=query_embedding,
            top_k=self._settings.search_top_k_chunks,
        )

        recommendations: list[RecommendationItem] = []
        seen: set[str] = set()
        for hit in hits:
            video_id = hit.get("video_id") or ""
            if not video_id or video_id in seen or video_id in exclude:
                continue
            seen.add(video_id)

            video = self._registry.get_video(video_id)
            if not video:
                continue
            if not video.get("recommendations_enabled"):
                continue

            if video.get("preferred_creator_only"):
                preferred_channel = video.get("channel", "")
                if preferred_channel and hit.get("channel") != preferred_channel:
                    if not video.get("allow_other_creators"):
                        continue

            confidence = round(min(1.0, hit["relevance_score"] + 0.15), 2)
            recommendations.append(
                RecommendationItem(
                    video_id=video_id,
                    title=hit.get("title", ""),
                    channel=hit.get("channel", ""),
                    thumbnail=hit.get("thumbnail", ""),
                    url=hit.get("url", ""),
                    why_recommended=_why_recommended(video, query),
                    whats_different=_whats_different(video, hit),
                    confidence=confidence,
                    already_saved=True,
                )
            )
            if len(recommendations) >= limit:
                break

        return recommendations


def _why_recommended(video: dict, query: str) -> str:
    goal = video.get("goal") or ""
    if goal:
        return f"Aligns with your saved goal: {goal}"
    style = (video.get("preferred_style") or "").replace("_", " ")
    if style:
        return f"Matches your preferred {style} style for '{query}'"
    return "Related to your saved memories and current question"


def _whats_different(video: dict, hit: dict) -> str:
    difficulty = video.get("difficulty") or ""
    if difficulty:
        return f"Saved at {difficulty} level — may offer a different angle than your top hit."
    channel = hit.get("channel") or video.get("channel") or "another creator"
    return f"Alternative perspective from {channel}."
