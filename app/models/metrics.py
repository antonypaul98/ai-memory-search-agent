"""Debug observability metrics for AHME pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field


class IngestMetrics(BaseModel):
    metadata_ms: float = 0.0
    transcript_ms: float = 0.0
    capsule_ms: float = 0.0
    chunking_ms: float = 0.0
    embedding_ms: float = 0.0
    storage_ms: float = 0.0
    duplicate_urls_removed: int = 0
    exact_duplicate_chunks_removed: int = 0
    near_duplicate_chunks_suppressed: int = 0
    embeddings_avoided: int = 0
    estimated_bytes_saved: int = 0


class SearchMetrics(BaseModel):
    total_ms: float = 0.0
    routing_ms: float = 0.0
    capsule_ms: float = 0.0
    section_ms: float = 0.0
    evidence_ms: float = 0.0
    lexical_ms: float = 0.0
    fusion_ms: float = 0.0
    mmr_ms: float = 0.0
    synthesis_ms: float = 0.0
    cache_hit: bool = False
    cache_type: str = ""
    pipeline: str = "flat"
    videos_considered: int = 0
    sections_searched: int = 0
    evidence_chunks_searched: int = 0
    duplicate_embeddings_avoided: int = 0
    estimated_llm_tokens: int = 0


class DebugMetrics(BaseModel):
    ingest: IngestMetrics | None = None
    search: SearchMetrics | None = None
