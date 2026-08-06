"""Universal memory orchestration — ties lifecycle, trust, and graph."""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import Settings, get_settings
from app.db.memory_store import MemoryStore, get_memory_store
from app.models.capsule import MemoryCapsule
from app.models.lifecycle import MemoryLifecycleState
from app.models.reflection import ReflectionInput
from app.models.trust import VerificationStatus
from app.models.universal_memory import MemoryEmbeddingRefs, MemoryProvenance, UniversalMemory
from app.models.video import SourceType, VideoMetadata
from app.services.knowledge_graph_service import KnowledgeGraphService
from app.services.memory_lifecycle_service import MemoryLifecycleService
from app.services.trust_engine import TrustEngine


class UniversalMemoryService:
    """Create and update universal memory records for all ingest paths."""

    def __init__(
        self,
        settings: Settings | None = None,
        store: MemoryStore | None = None,
        lifecycle: MemoryLifecycleService | None = None,
        trust: TrustEngine | None = None,
        graph: KnowledgeGraphService | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._store = store or get_memory_store(self._settings)
        self._lifecycle = lifecycle or MemoryLifecycleService(self._settings, self._store)
        self._trust = trust or TrustEngine(self._settings, self._store)
        self._graph = graph or KnowledgeGraphService(self._settings)

    def begin_capture(
        self,
        *,
        user_id: str,
        source_type: SourceType,
        external_id: str,
        canonical_url: str,
        title: str = "",
        source_author: str = "",
        ingest_url: str | None = None,
        job_id: str | None = None,
        capture_id: str | None = None,
    ) -> UniversalMemory:
        now = datetime.now(timezone.utc).isoformat()
        provenance = MemoryProvenance(
            ingest_url=ingest_url or canonical_url,
            job_id=job_id,
            capture_id=capture_id,
            captured_at=now,
        )
        memory = self._store.upsert(
            user_id=user_id,
            source_type=source_type,
            external_id=external_id,
            canonical_url=canonical_url,
            title=title or external_id,
            source_author=source_author,
            provenance=provenance,
            lifecycle_state=MemoryLifecycleState.CAPTURED,
            verification_status=VerificationStatus.UNVERIFIED,
        )
        return memory

    def finalize_ingest(
        self,
        *,
        user_id: str,
        metadata: VideoMetadata,
        capsule: MemoryCapsule,
        reflection: ReflectionInput | None,
        chunk_count: int,
        embedding_model: str,
        transcript_source: str,
        has_capsule: bool,
        increment_content_version: bool = True,
    ) -> UniversalMemory:
        """Run full lifecycle, graph, and trust pipeline after successful vector store."""
        now = datetime.now(timezone.utc).isoformat()
        provenance = MemoryProvenance(
            ingest_url=metadata.webpage_url,
            captured_at=now,
        )
        memory = self._store.upsert(
            user_id=user_id,
            source_type=metadata.source_type,
            external_id=metadata.video_id,
            canonical_url=metadata.webpage_url,
            title=metadata.title,
            source_author=metadata.channel,
            provenance=provenance,
            lifecycle_state=MemoryLifecycleState.CAPTURED,
            verification_status=VerificationStatus.UNVERIFIED,
            increment_content_version=increment_content_version,
            version_reason="ingest_started",
        )
        self._lifecycle.advance_pipeline(
            memory_id=memory.memory_id,
            user_id=user_id,
            target_state=MemoryLifecycleState.ENRICHED,
            reason="metadata_transcript_capsule_ready",
        )

        evidence_ids = [
            f"{metadata.source_type.value}_{metadata.video_id}_{idx}" for idx in range(chunk_count)
        ]
        embedding_refs = MemoryEmbeddingRefs(
            capsule_doc_id=f"capsule_{metadata.video_id}" if has_capsule else None,
            section_doc_ids=[
                f"section_{metadata.video_id}_{idx}" for idx in range(len(capsule.sections))
            ],
            evidence_doc_ids=evidence_ids,
            embedding_model=embedding_model,
            chunk_count=chunk_count,
        )

        meta = {
            "duration_sec": metadata.duration,
            "transcript_source": transcript_source,
            "description_excerpt": (metadata.description or "")[:500],
            "topics": capsule.topics,
        }

        verification = VerificationStatus.VERIFIED if chunk_count > 0 and has_capsule else (
            VerificationStatus.PARTIAL if chunk_count > 0 else VerificationStatus.UNVERIFIED
        )

        memory = self._store.upsert(
            user_id=user_id,
            source_type=metadata.source_type,
            external_id=metadata.video_id,
            canonical_url=metadata.webpage_url,
            title=metadata.title,
            source_author=metadata.channel,
            provenance=memory.provenance,
            metadata=meta,
            embedding_refs=embedding_refs,
            verification_status=verification,
            increment_content_version=False,
        )

        memory = self._lifecycle.advance_pipeline(
            memory_id=memory.memory_id,
            user_id=user_id,
            target_state=MemoryLifecycleState.EMBEDDED,
            reason="ingest_vectors_stored",
        )

        rel_counts = self._graph.connect_memory(
            memory=memory,
            metadata=metadata,
            capsule=capsule,
            reflection=reflection,
        )
        memory = self._store.upsert(
            user_id=user_id,
            source_type=memory.source_type,
            external_id=memory.external_id,
            canonical_url=memory.canonical_url,
            title=memory.title,
            source_author=memory.source_author,
            provenance=memory.provenance,
            metadata=memory.metadata,
            embedding_refs=memory.embedding_refs,
            verification_status=memory.verification_status,
            relationship_summary=rel_counts,
        )
        memory = self._lifecycle.advance_pipeline(
            memory_id=memory.memory_id,
            user_id=user_id,
            target_state=MemoryLifecycleState.CONNECTED,
            reason="graph_linked",
        )

        memory = self._lifecycle.advance_pipeline(
            memory_id=memory.memory_id,
            user_id=user_id,
            target_state=MemoryLifecycleState.VERIFIED,
            reason="verification_complete",
        )

        trust = self._trust.compute(
            memory=memory,
            chunk_count=chunk_count,
            has_capsule=has_capsule,
        )
        memory = self._store.upsert(
            user_id=user_id,
            source_type=memory.source_type,
            external_id=memory.external_id,
            canonical_url=memory.canonical_url,
            title=memory.title,
            source_author=memory.source_author,
            provenance=memory.provenance,
            metadata=memory.metadata,
            embedding_refs=memory.embedding_refs,
            verification_status=memory.verification_status,
            trust=trust,
            relationship_summary=memory.relationship_summary,
        )

        if trust.overall >= TrustEngine.TRUSTED_THRESHOLD:
            memory = self._lifecycle.advance_pipeline(
                memory_id=memory.memory_id,
                user_id=user_id,
                target_state=MemoryLifecycleState.TRUSTED,
                reason="trust_threshold_met",
            )

        try:
            from app.services.memory_intelligence_service import MemoryIntelligenceService

            MemoryIntelligenceService(settings=self._settings).on_memory_indexed(
                user_id=user_id,
                metadata=metadata,
                capsule=capsule,
                reflection=reflection,
                memory_id=memory.memory_id,
            )
        except Exception:
            # Intelligence layer must not break ingest.
            pass

        return memory

    def mark_existing_indexed(
        self,
        *,
        user_id: str,
        source_type: SourceType,
        external_id: str,
        canonical_url: str,
        title: str,
        source_author: str = "",
    ) -> UniversalMemory:
        """Ensure a skipped/already-indexed item has a trusted memory record."""
        existing = self._store.get_by_external(
            user_id=user_id, source_type=source_type, external_id=external_id
        )
        if existing and existing.lifecycle_state in {
            MemoryLifecycleState.TRUSTED,
            MemoryLifecycleState.VERIFIED,
        }:
            return existing

        memory = self.begin_capture(
            user_id=user_id,
            source_type=source_type,
            external_id=external_id,
            canonical_url=canonical_url,
            title=title,
            source_author=source_author,
        )
        trust = self._trust.compute(memory=memory, chunk_count=1, has_capsule=True)
        memory = self._store.upsert(
            user_id=user_id,
            source_type=source_type,
            external_id=external_id,
            canonical_url=canonical_url,
            title=title,
            source_author=source_author,
            provenance=memory.provenance,
            verification_status=VerificationStatus.VERIFIED,
            trust=trust,
        )
        return self._lifecycle.advance_pipeline(
            memory_id=memory.memory_id,
            user_id=user_id,
            target_state=MemoryLifecycleState.TRUSTED,
            reason="already_indexed",
        )
