"""
Generic connector ingest — indexes any SourceConnector into universal memory + Chroma.

YouTube continues to use IngestService for rich YouTubeMemory pipeline; this path
handles web/pdf/github (and can also ingest YouTube when called explicitly).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from app.config import Settings, get_settings
from app.core.embeddings import embed_texts
from app.core.exceptions import AppError
from app.db.hierarchical_store import HierarchicalStore, store_capsule_json
from app.db.repositories.memory_repository import MemoryRepository
from app.db.schema import bump_index_version, invalidate_semantic_cache, migrate
from app.db.video_registry import get_video_registry
from app.models.reflection import ReflectionInput
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.models.video import IngestResultItem, IngestStageRecord, SourceType, VideoMetadata
from app.services.capsule_service import build_capsule_with_optional_llm
from app.services.cross_duplicate_service import CrossConnectorDuplicateDetector
from app.services.deduplication_service import dedupe_chunk_texts
from app.services.enrichment_service import enrich_video
from app.services.fts_index import FTSIndex
from app.services.sources import get_connector_registry
from app.services.sources.base_source import ProcessingStatus, SourceRef, TranscriptKind
from app.services.universal_memory_service import UniversalMemoryService
from app.utils.chunking import chunk_transcript


class ConnectorIngestService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._repository = MemoryRepository(self._settings)
        self._registry = get_video_registry(self._settings)
        self._hstore = HierarchicalStore(self._settings)
        self._fts = FTSIndex(self._settings)
        self._memory_os = UniversalMemoryService(self._settings)
        self._dupes = CrossConnectorDuplicateDetector(self._settings)
        migrate(self._settings)

    def ingest_url(
        self,
        url: str,
        *,
        user_id: str,
        force_refresh: bool = False,
        reflection: ReflectionInput | None = None,
        selected_text: str = "",
        stage_callback=None,
        connector_id: str | None = None,
        ref_extra: dict | None = None,
    ) -> IngestResultItem:
        started = time.perf_counter()
        stages: list[IngestStageRecord] = []

        def record(stage: str, detail: str = "") -> None:
            stages.append(
                IngestStageRecord(
                    stage=stage,
                    detail=detail,
                    elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
                )
            )
            if stage_callback:
                try:
                    stage_callback(stage, detail)
                except Exception:
                    pass

        record(ProcessingStatus.QUEUED.value, url)
        try:
            connectors = get_connector_registry()
            connector = connectors.get(connector_id) if connector_id else connectors.resolve_for_url(url)
            ref = connector.parse_ref(url)
            if ref_extra:
                ref.extra.update(ref_extra)
            if selected_text:
                ref.extra["selected_text"] = selected_text

            record(ProcessingStatus.METADATA.value)
            item = connector.fetch_metadata(ref)
            dupe = self._dupes.check(
                user_id=user_id,
                canonical_url=item.canonical_url,
                content_hash=item.content_hash,
            )
            if dupe.is_duplicate and not force_refresh:
                record(ProcessingStatus.COMPLETED.value, dupe.reason)
                return IngestResultItem(
                    url=url,
                    success=True,
                    skipped=True,
                    video_id=item.external_id,
                    title=item.title,
                    channel=item.author,
                    webpage_url=item.canonical_url,
                    stages=stages,
                    elapsed_ms=_elapsed(started),
                )

            record(ProcessingStatus.TRANSCRIPT.value)
            payload = connector.fetch_transcript(ref)
            transcript = TranscriptResult(
                video_id=item.external_id,
                canonical_url=item.canonical_url,
                segments=[
                    TranscriptSegment(
                        text=s.text,
                        start_time_sec=s.start_time_sec,
                        duration_sec=s.duration_sec,
                    )
                    for s in payload.segments
                ],
                full_text=payload.full_text,
                language=payload.language or item.language,
                is_generated=payload.kind == TranscriptKind.AUTO_GENERATED,
            )

            metadata = VideoMetadata(
                video_id=item.external_id,
                title=item.title,
                description=item.description,
                channel=item.author or item.source_type.value,
                thumbnail=item.thumbnail,
                duration=item.duration_sec,
                webpage_url=item.canonical_url,
                source_type=item.source_type,
                channel_id="",
                published_at=item.published_at,
                language=item.language,
                tags=item.tags,
                categories=item.categories,
                content_hash=item.content_hash,
                connector_id=item.connector_id,
                raw_metadata=dict(item.raw_metadata),
            )

            record(ProcessingStatus.CHUNKING.value)
            capsule = build_capsule_with_optional_llm(
                metadata=metadata, transcript=transcript, reflection=reflection
            )
            chunks = chunk_transcript(
                transcript.segments,
                chunk_size=self._settings.chunk_size,
                chunk_overlap=self._settings.chunk_overlap,
            )
            if not chunks:
                record(ProcessingStatus.FAILED.value, "Empty content")
                return IngestResultItem(
                    url=url,
                    success=False,
                    video_id=item.external_id,
                    title=item.title,
                    error="No content to index.",
                    stages=stages,
                    elapsed_ms=_elapsed(started),
                )

            unique_texts, _ = dedupe_chunk_texts([c.text for c in chunks])
            remaining = set(unique_texts)
            filtered = []
            for c in chunks:
                if c.text in remaining:
                    filtered.append(c)
                    remaining.discard(c.text)
            chunks = filtered
            chunk_texts = [c.text for c in chunks]

            record(ProcessingStatus.EMBEDDING.value)
            all_embeddings: list[list[float]] = []
            batch_size = self._settings.embedding_batch_size
            for i in range(0, len(chunk_texts), batch_size):
                all_embeddings.extend(
                    embed_texts(chunk_texts[i : i + batch_size], settings=self._settings)
                )
            capsule_emb = embed_texts(
                [capsule.short_summary or capsule.one_line_memory], settings=self._settings
            )[0]
            section_texts = [f"{s.title}. {s.summary}" for s in capsule.sections] or [
                capsule.short_summary
            ]
            section_embs = embed_texts(section_texts, settings=self._settings)

            enrichment = enrich_video(
                title=metadata.title,
                description=metadata.description,
                channel=metadata.channel,
                transcript_text=transcript.full_text,
                chunk_texts=chunk_texts,
            )
            transcript_source = (
                "auto_generated" if transcript.is_generated else "manual_captions"
            )

            record(ProcessingStatus.INDEXED.value)
            self._hstore.delete_video(metadata.video_id)
            self._fts.delete_video(metadata.video_id)
            chunk_count = self._repository.upsert_chunks(
                video_id=metadata.video_id,
                user_id=user_id,
                url=metadata.webpage_url,
                title=metadata.title,
                channel=metadata.channel,
                thumbnail=metadata.thumbnail,
                duration=metadata.duration,
                transcript_source=transcript_source,
                chunks=chunks,
                embeddings=all_embeddings,
                embedding_model=self._settings.embedding_model,
                description=metadata.description,
                one_line_memory=enrichment.one_line_memory,
                why_saved=enrichment.why_saved,
                action_items=enrichment.action_items,
                language=metadata.language,
                tags=metadata.tags,
                categories=metadata.categories,
                source_type=metadata.source_type,
                connector_id=metadata.connector_id,
            )

            if self._settings.hierarchical_retrieval_enabled:
                self._hstore.upsert_capsule(capsule, capsule_emb)
                if capsule.sections:
                    self._hstore.upsert_sections(metadata.video_id, capsule.sections, section_embs)
                store_capsule_json(self._settings, metadata.video_id, capsule)
                self._fts.upsert(
                    video_id=metadata.video_id,
                    level="capsule",
                    doc_id=f"capsule_{metadata.video_id}",
                    title=capsule.title,
                    body=f"{capsule.short_summary} {' '.join(capsule.topics)}",
                )
                for idx, section in enumerate(capsule.sections):
                    self._fts.upsert(
                        video_id=metadata.video_id,
                        level="section",
                        doc_id=f"section_{metadata.video_id}_{idx}",
                        title=section.title,
                        body=section.summary,
                    )
                for chunk in chunks:
                    self._fts.upsert(
                        video_id=metadata.video_id,
                        level="evidence",
                        doc_id=f"{metadata.source_type.value}_{metadata.video_id}_{chunk.chunk_index}",
                        title=metadata.title,
                        body=chunk.text,
                    )

            bump_index_version(self._settings)
            invalidate_semantic_cache(self._settings)
            self._registry.upsert_video(
                video_id=metadata.video_id,
                user_id=user_id,
                url=metadata.webpage_url,
                title=metadata.title,
                channel=metadata.channel,
                reflection=reflection,
            )
            memory = self._memory_os.finalize_ingest(
                user_id=user_id,
                metadata=metadata,
                capsule=capsule,
                reflection=reflection,
                chunk_count=chunk_count,
                embedding_model=self._settings.embedding_model,
                transcript_source=transcript_source,
                has_capsule=self._settings.hierarchical_retrieval_enabled,
            )
            self._dupes.register(
                user_id=user_id,
                canonical_url=item.canonical_url,
                content_hash=item.content_hash,
                source_type=item.source_type.value,
                connector_id=item.connector_id,
                external_id=item.external_id,
                memory_id=memory.memory_id,
            )

            record(ProcessingStatus.COMPLETED.value, f"{chunk_count} chunks")
            return IngestResultItem(
                url=url,
                success=True,
                video_id=metadata.video_id,
                title=metadata.title,
                channel=metadata.channel,
                thumbnail=metadata.thumbnail,
                duration=metadata.duration,
                webpage_url=metadata.webpage_url,
                chunk_count=chunk_count,
                transcript_source=transcript_source,
                stages=stages,
                elapsed_ms=_elapsed(started),
            )
        except AppError as exc:
            record(ProcessingStatus.FAILED.value, exc.message)
            return IngestResultItem(
                url=url,
                success=False,
                error=exc.message,
                stages=stages,
                elapsed_ms=_elapsed(started),
            )
        except Exception as exc:
            record(ProcessingStatus.FAILED.value, str(exc))
            return IngestResultItem(
                url=url,
                success=False,
                error=f"Unexpected error: {exc}",
                stages=stages,
                elapsed_ms=_elapsed(started),
            )

    def ingest_pdf_bytes(
        self,
        data: bytes,
        *,
        user_id: str,
        filename: str = "document.pdf",
        force_refresh: bool = False,
        reflection: ReflectionInput | None = None,
        stage_callback=None,
    ) -> IngestResultItem:
        from app.services.deduplication_service import hash_text

        external_id = hash_text(data)[:24]
        url = f"pdf://{external_id}"
        return self.ingest_url(
            url,
            user_id=user_id,
            force_refresh=force_refresh,
            reflection=reflection,
            stage_callback=stage_callback,
            connector_id="pdf.v1",
            ref_extra={"bytes": data, "filename": filename},
        )


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
