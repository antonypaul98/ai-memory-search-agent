"""
Adaptive Hierarchical Memory Engine — coarse-to-fine retrieval orchestrator.

Internal architecture (not a proprietary algorithm):
Query → intent classification → capsule retrieval → video selection →
section retrieval → evidence retrieval → deduplication → synthesis → cache
"""

from __future__ import annotations

import time
from typing import Any

from app.config import Settings, get_settings
from app.core.embeddings import embed_query
from app.db.hierarchical_store import HierarchicalStore
from app.db.repositories.memory_repository import MemoryRepository
from app.models.metrics import SearchMetrics
from app.services.fts_index_factory import get_fts_index
from app.services.mmr import mmr_select
from app.services.query_router import QueryType, route_query
from app.services.rrf import reciprocal_rank_fusion
from app.services.semantic_cache import SemanticCache


class AdaptiveHierarchicalMemoryEngine:
    """Hierarchical retrieval with hybrid fusion and MMR; falls back on errors."""

    def __init__(
        self,
        settings: Settings | None = None,
        repository: MemoryRepository | None = None,
        store: HierarchicalStore | None = None,
        fts: Any | None = None,
        cache: SemanticCache | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._repository = repository or MemoryRepository(self._settings)
        self._store = store or HierarchicalStore(self._settings)
        self._fts = fts or get_fts_index(self._settings)
        self._cache = cache or SemanticCache(self._settings)

    def retrieve(
        self,
        query: str,
        *,
        top_k: int | None = None,
        user_id: str | None = None,
        video_filter: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], SearchMetrics]:
        from app.models.user import LOCAL_DEFAULT_USER_ID

        owner = user_id or LOCAL_DEFAULT_USER_ID
        metrics = SearchMetrics(pipeline="hierarchical")
        t0 = time.perf_counter()

        if not self._settings.hierarchical_retrieval_enabled:
            return self._flat_fallback(query, top_k or 6, metrics, t0, user_id=owner, pipeline="flat")

        try:
            return self._hierarchical_retrieve(
                query, top_k=top_k, video_filter=video_filter, metrics=metrics, t0=t0, user_id=owner
            )
        except Exception:
            metrics.pipeline = "flat_fallback"
            return self._flat_fallback(query, top_k or 6, metrics, t0, user_id=owner, pipeline="flat_fallback")

    def _hierarchical_retrieve(
        self,
        query: str,
        *,
        top_k: int | None,
        video_filter: list[str] | None,
        metrics: SearchMetrics,
        t0: float,
        user_id: str,
    ) -> tuple[list[dict[str, Any]], SearchMetrics]:
        tr0 = time.perf_counter()
        route = route_query(query, settings=self._settings)
        metrics.routing_ms = (time.perf_counter() - tr0) * 1000
        query_type = route.query_types[0].value if route.query_types else "exact_lookup"

        embedding = embed_query(query, settings=self._settings)
        if route.allow_cache:
            cached = self._cache.get(
                question=query,
                query_embedding=embedding,
                query_type=query_type,
                user_id=user_id,
            )
            if cached:
                metrics.cache_hit = True
                metrics.cache_type = cached.get("cache_type", "")
                metrics.total_ms = (time.perf_counter() - t0) * 1000
                return cached["answer"].get("chunks", []), metrics

        tc0 = time.perf_counter()
        capsule_hits = self._store.search_level(
            self._settings.capsule_collection_name,
            embedding,
            top_k=self._settings.capsule_top_k,
            video_ids=video_filter,
        )
        metrics.capsule_ms = (time.perf_counter() - tc0) * 1000
        metrics.videos_considered = len({h["video_id"] for h in capsule_hits if h.get("video_id")})

        selected_videos = [
            h["video_id"]
            for h in sorted(capsule_hits, key=lambda x: x["relevance_score"], reverse=True)
            if h.get("video_id")
        ][: route.video_top_k]

        if not selected_videos and capsule_hits:
            selected_videos = [capsule_hits[0]["video_id"]]

        ts0 = time.perf_counter()
        section_hits = self._store.search_level(
            self._settings.section_collection_name,
            embedding,
            top_k=route.section_top_k,
            video_ids=selected_videos or None,
        )
        metrics.section_ms = (time.perf_counter() - ts0) * 1000
        metrics.sections_searched = len(section_hits)

        te0 = time.perf_counter()
        evidence_hits = self._repository.search(
            query_embedding=embedding,
            top_k=route.evidence_top_k,
            user_id=user_id,
        )
        if selected_videos:
            evidence_hits = [h for h in evidence_hits if h.get("video_id") in selected_videos]
        metrics.evidence_ms = (time.perf_counter() - te0) * 1000
        metrics.evidence_chunks_searched = len(evidence_hits)

        tl0 = time.perf_counter()
        lexical = self._fts.search(
            query,
            limit=20,
            video_ids=selected_videos or None,
            user_id=user_id,
        )
        metrics.lexical_ms = (time.perf_counter() - tl0) * 1000

        tf0 = time.perf_counter()
        ranked_lists = [
            [h.get("doc_id") or f"capsule_{h.get('video_id')}" for h in capsule_hits],
            [
                h.get("doc_id")
                or f"section_{h.get('video_id')}_{h.get('section_index', i)}"
                for i, h in enumerate(section_hits)
            ],
            [
                h.get("doc_id")
                or f"evidence_{h.get('video_id')}_{h.get('start_time', i)}"
                for i, h in enumerate(evidence_hits)
            ],
            [h.get("doc_id", f"lex_{i}") for i, h in enumerate(lexical)],
        ]
        fused = reciprocal_rank_fusion(ranked_lists, k=self._settings.rrf_k)
        fusion_scores = {doc_id: score for doc_id, score in fused}

        for hit in evidence_hits + section_hits + capsule_hits + lexical:
            doc_key = (
                hit.get("doc_id")
                or f"evidence_{hit.get('video_id')}_{hit.get('start_time', 0)}"
            )
            hit["relevance_score"] = max(
                hit.get("relevance_score", 0.0),
                fusion_scores.get(doc_key, 0.0),
            )

        combined = {id(h): h for h in evidence_hits + section_hits + lexical}
        candidates = sorted(combined.values(), key=lambda h: h["relevance_score"], reverse=True)
        metrics.fusion_ms = (time.perf_counter() - tf0) * 1000

        tm0 = time.perf_counter()
        limit = top_k or route.evidence_top_k
        selected = mmr_select(candidates, limit=limit, lambda_=self._settings.mmr_lambda)
        metrics.mmr_ms = (time.perf_counter() - tm0) * 1000
        metrics.pipeline = "hierarchical"
        metrics.total_ms = (time.perf_counter() - t0) * 1000

        if route.allow_cache and selected:
            self._cache.put(
                question=query,
                query_embedding=embedding,
                answer={"chunks": selected},
                query_type=query_type,
                user_id=user_id,
            )

        return selected, metrics

    def _flat_fallback(
        self,
        query: str,
        top_k: int,
        metrics: SearchMetrics,
        t0: float,
        *,
        pipeline: str = "flat",
        user_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], SearchMetrics]:
        from app.models.user import LOCAL_DEFAULT_USER_ID

        owner = user_id or LOCAL_DEFAULT_USER_ID
        if metrics.pipeline in {"", "hierarchical"}:
            metrics.pipeline = pipeline
        hits = self._repository.search(
            query_embedding=embed_query(query, settings=self._settings),
            top_k=max(top_k, self._settings.search_top_k_chunks),
            user_id=owner,
        )
        grouped: dict[str, dict] = {}
        for hit in hits:
            vid = hit.get("video_id") or ""
            if not vid:
                continue
            if vid not in grouped or hit["relevance_score"] > grouped[vid]["relevance_score"]:
                grouped[vid] = hit
        selected = sorted(grouped.values(), key=lambda h: h["relevance_score"], reverse=True)[:top_k]
        metrics.total_ms = (time.perf_counter() - t0) * 1000
        return selected, metrics
