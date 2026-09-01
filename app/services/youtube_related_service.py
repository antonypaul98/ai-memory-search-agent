"""Related YouTube memories — shared topics, creators, entities, transcript affinity."""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from app.core.embeddings import embed_query
from app.db.repositories.memory_repository import MemoryRepository
from app.db.youtube_memory_store_factory import get_youtube_memory_store
from app.models.youtube_memory import RelatedMemoriesResponse, RelatedMemoryItem
from app.services.knowledge_graph_service import KnowledgeGraphService


class YouTubeRelatedService:
    def __init__(
        self,
        settings: Settings | None = None,
        store: Any | None = None,
        repository: MemoryRepository | None = None,
        graph: KnowledgeGraphService | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._store = store or get_youtube_memory_store(self._settings)
        self._repository = repository or MemoryRepository(self._settings)
        self._graph = graph or KnowledgeGraphService(settings=self._settings)

    def related(
        self,
        video_id: str,
        *,
        user_id: str,
        limit: int = 8,
    ) -> RelatedMemoriesResponse:
        source = self._store.get(video_id, user_id=user_id)
        if not source:
            return RelatedMemoriesResponse(video_id=video_id, items=[])

        scored: dict[str, RelatedMemoryItem] = {}

        # Shared creator
        for peer in self._store.list_for_user(user_id, limit=200):
            if peer.video_id == video_id:
                continue
            if peer.channel and peer.channel == source.channel:
                scored[peer.video_id] = RelatedMemoryItem(
                    video_id=peer.video_id,
                    title=peer.title,
                    channel=peer.channel,
                    url=peer.url,
                    relationship="shared_creator",
                    strength=0.7,
                    shared_topics=[],
                    shared_entities=[],
                )

        # Shared tags / topics
        source_tags = {t.lower() for t in source.tags}
        for peer in self._store.list_for_user(user_id, limit=200):
            if peer.video_id == video_id:
                continue
            shared = sorted(source_tags & {t.lower() for t in peer.tags})
            if not shared:
                continue
            strength = min(1.0, 0.4 + 0.1 * len(shared))
            existing = scored.get(peer.video_id)
            if existing:
                existing.strength = max(existing.strength, strength)
                existing.shared_topics = shared[:8]
                if existing.relationship == "shared_creator":
                    existing.relationship = "shared_creator_and_topics"
            else:
                scored[peer.video_id] = RelatedMemoryItem(
                    video_id=peer.video_id,
                    title=peer.title,
                    channel=peer.channel,
                    url=peer.url,
                    relationship="shared_topics",
                    strength=strength,
                    shared_topics=shared[:8],
                )

        # Knowledge-graph entity overlap
        try:
            from app.db.memory_store import get_memory_store

            mem = get_memory_store(self._settings).get_by_external(
                user_id=user_id, source_type=source.source_type, external_id=video_id
            )
            if mem:
                entities = self._graph.entities_for_memory(mem.memory_id, user_id=user_id)
                entity_names = {e.name.lower() for e in entities}
                for peer in self._store.list_for_user(user_id, limit=100):
                    if peer.video_id == video_id:
                        continue
                    peer_mem = get_memory_store(self._settings).get_by_external(
                        user_id=user_id,
                        source_type=peer.source_type,
                        external_id=peer.video_id,
                    )
                    if not peer_mem:
                        continue
                    peer_ents = self._graph.entities_for_memory(
                        peer_mem.memory_id, user_id=user_id
                    )
                    shared_e = sorted(
                        entity_names & {e.name.lower() for e in peer_ents}
                    )
                    if not shared_e:
                        continue
                    strength = min(1.0, 0.5 + 0.08 * len(shared_e))
                    existing = scored.get(peer.video_id)
                    if existing:
                        existing.strength = max(existing.strength, strength)
                        existing.shared_entities = shared_e[:8]
                    else:
                        scored[peer.video_id] = RelatedMemoryItem(
                            video_id=peer.video_id,
                            title=peer.title,
                            channel=peer.channel,
                            url=peer.url,
                            relationship="shared_entities",
                            strength=strength,
                            shared_entities=shared_e[:8],
                        )
        except Exception:
            pass

        # Semantic similarity from transcript chunks
        try:
            query = f"{source.title} {source.description[:400]}"
            emb = embed_query(query, settings=self._settings)
            hits = self._repository.search(query_embedding=emb, top_k=20, user_id=user_id)
            for hit in hits:
                vid = hit.get("video_id") or ""
                if not vid or vid == video_id:
                    continue
                strength = min(1.0, float(hit.get("relevance_score") or 0))
                existing = scored.get(vid)
                if existing:
                    existing.strength = max(existing.strength, strength)
                    if existing.relationship.startswith("shared"):
                        existing.relationship = f"{existing.relationship}+similar_transcript"
                    else:
                        existing.relationship = "similar_transcript"
                else:
                    scored[vid] = RelatedMemoryItem(
                        video_id=vid,
                        title=hit.get("title") or "",
                        channel=hit.get("channel") or "",
                        url=hit.get("url") or "",
                        relationship="similar_transcript",
                        strength=strength,
                    )
        except Exception:
            pass

        items = sorted(scored.values(), key=lambda i: i.strength, reverse=True)[:limit]
        return RelatedMemoriesResponse(video_id=video_id, items=items)
