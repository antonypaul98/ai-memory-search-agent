"""
Ingest orchestration: bounded async concurrency, deduplication, and progress tracking.

Bounded asynchronous ingestion with semaphore-controlled concurrency, singleton
embedding reuse, batched vector generation, deduplication and idempotent vector upserts.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from enum import Enum

from app.config import Settings, get_settings
from app.core.embeddings import embed_texts
from app.core.exceptions import AppError, InvalidYouTubeURLError
from app.db.repositories.memory_repository import MemoryRepository
from app.db.video_registry import VideoRegistry, get_video_registry
from app.models.reflection import ReflectionInput
from app.models.video import IngestResponse, IngestResultItem, IngestStageRecord, SourceType
from app.db.hierarchical_store import HierarchicalStore, store_capsule_json
from app.db.schema import get_connection, migrate
from app.services.capsule_service import build_capsule_with_optional_llm
from app.services.deduplication_service import dedupe_chunk_texts, hash_text
from app.services.enrichment_service import enrich_video
from app.services.fts_index_factory import get_fts_index
from app.services.metadata_service import MetadataService
from app.services.semantic_cache import SemanticCache
from app.services.transcript_service import TranscriptService
from app.utils.chunking import chunk_transcript
from app.utils.url_parser import parse_youtube_url
from app.services.universal_memory_service import UniversalMemoryService
from app.db.youtube_memory_store import new_memory_id
from app.db.youtube_memory_store_factory import get_youtube_memory_store
from app.models.youtube_memory import YouTubeMemory
from app.services.sources.base_source import (
    ProcessingStatus,
    TranscriptAvailability,
    TranscriptKind,
)
from app.services.youtube_duplicate_service import YouTubeDuplicateDetector

MAX_BATCH_SIZE = 20

_TRANSCRIPT_CACHE: dict[str, object] = {}


def clear_transcript_cache() -> None:
    """Clear cached transcripts — used in tests and forced re-ingest."""
    _TRANSCRIPT_CACHE.clear()


class IngestStage(str, Enum):
    QUEUED = "queued"
    METADATA = "metadata"
    TRANSCRIPT = "transcript"
    CAPSULE = "capsule"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    STORING = "storing"
    INDEXED = "indexed"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRY = "retry"


class IngestService:
    """Orchestrate connector-backed URL ingestion into ChromaDB."""

    def __init__(
        self,
        settings: Settings | None = None,
        metadata_service: MetadataService | None = None,
        transcript_service: TranscriptService | None = None,
        repository: MemoryRepository | None = None,
        registry: VideoRegistry | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._metadata = metadata_service or MetadataService()
        self._transcript = transcript_service or TranscriptService()
        self._repository = repository or MemoryRepository(self._settings)
        self._registry = registry or get_video_registry(self._settings)
        self._hstore = HierarchicalStore(self._settings)
        self._fts = get_fts_index(self._settings)
        self._memory_os = UniversalMemoryService(self._settings)
        self._yt_store = get_youtube_memory_store(self._settings)
        self._dupes = YouTubeDuplicateDetector(self._yt_store)
        migrate(self._settings)

    def ingest_batch(
        self,
        urls: list[str],
        *,
        reflection: ReflectionInput | None = None,
        force_refresh: bool = False,
        user_id: str | None = None,
    ) -> IngestResponse:
        """Ingest URLs with bounded async concurrency."""
        if len(urls) > MAX_BATCH_SIZE:
            raise ValueError(f"Batch limit is {MAX_BATCH_SIZE} URLs.")

        deduped_urls = _dedupe_urls(urls)
        started = time.perf_counter()
        results = asyncio.run(
            self._ingest_batch_async(
                deduped_urls,
                reflection=reflection,
                force_refresh=force_refresh,
                user_id=user_id,
            )
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        succeeded = sum(1 for item in results if item.success and not item.skipped)
        skipped = sum(1 for item in results if item.skipped)
        failed = sum(1 for item in results if not item.success)
        return IngestResponse(
            total=len(results),
            succeeded=succeeded,
            failed=failed,
            skipped=skipped,
            elapsed_ms=elapsed_ms,
            results=results,
        )

    def ingest_single_url(
        self,
        url: str,
        *,
        user_id: str | None = None,
        reflection: ReflectionInput | None = None,
        force_refresh: bool = False,
        stage_callback=None,
        run_id: str | None = None,
        capture_id: str | None = None,
        playback_position_sec: float | None = None,
        user_notes: str = "",
        playlist_id: str | None = None,
        playlist_title: str | None = None,
    ) -> IngestResultItem:
        return self._ingest_one(
            url,
            reflection=reflection,
            force_refresh=force_refresh,
            user_id=user_id,
            stage_callback=stage_callback,
            run_id=run_id,
            capture_id=capture_id,
            playback_position_sec=playback_position_sec,
            user_notes=user_notes,
            playlist_id=playlist_id,
            playlist_title=playlist_title,
        )

    async def _ingest_batch_async(
        self,
        urls: list[str],
        *,
        reflection: ReflectionInput | None,
        force_refresh: bool,
        user_id: str | None = None,
    ) -> list[IngestResultItem]:
        semaphore = asyncio.Semaphore(self._settings.ingest_concurrency)

        async def _run(url: str) -> IngestResultItem:
            async with semaphore:
                return await asyncio.to_thread(
                    self._ingest_one,
                    url,
                    reflection=reflection,
                    force_refresh=force_refresh,
                    user_id=user_id,
                )

        return list(await asyncio.gather(*[_run(url) for url in urls]))

    def _ingest_one(
        self,
        url: str,
        *,
        reflection: ReflectionInput | None = None,
        force_refresh: bool = False,
        user_id: str | None = None,
        stage_callback=None,
        run_id: str | None = None,
        capture_id: str | None = None,
        playback_position_sec: float | None = None,
        user_notes: str = "",
        playlist_id: str | None = None,
        playlist_title: str | None = None,
    ) -> IngestResultItem:
        from app.models.user import LOCAL_DEFAULT_USER_ID

        owner_id = user_id or LOCAL_DEFAULT_USER_ID
        stages: list[IngestStageRecord] = []
        started = time.perf_counter()
        pipeline_id = run_id or new_memory_id()
        video_id_for_fail = ""

        def record(stage: IngestStage, detail: str = "") -> None:
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            stages.append(
                IngestStageRecord(stage=stage.value, detail=detail, elapsed_ms=elapsed)
            )
            try:
                self._yt_store.record_pipeline_stage(
                    run_id=pipeline_id,
                    user_id=owner_id,
                    video_id=video_id_for_fail,
                    capture_id=capture_id,
                    stage=stage.value,
                    detail=detail,
                    elapsed_ms=elapsed,
                )
            except Exception:
                pass
            if stage_callback:
                try:
                    stage_callback(stage.value, detail)
                except Exception:
                    pass

        record(IngestStage.QUEUED, url)
        if not url.strip():
            record(IngestStage.FAILED, "Empty URL")
            return IngestResultItem(
                url=url, success=False, error="URL cannot be empty.",
                stages=stages, elapsed_ms=_elapsed(started),
            )

        try:
            parsed = parse_youtube_url(url)
            video_id = parsed.video_id
            video_id_for_fail = video_id

            if not force_refresh and (
                self._registry.is_indexed(video_id, user_id=owner_id)
                or self._repository.video_exists(video_id, user_id=owner_id)
            ):
                record(IngestStage.SKIPPED, "Already indexed")
                video = self._registry.get_video(video_id) or {}
                self._memory_os.mark_existing_indexed(
                    user_id=owner_id,
                    source_type=SourceType.YOUTUBE,
                    external_id=video_id,
                    canonical_url=video.get("url") or url,
                    title=video.get("title") or video_id,
                    source_author=video.get("channel") or "",
                )
                return IngestResultItem(
                    url=url, success=True, skipped=True, video_id=video_id,
                    title=video.get("title"), channel=video.get("channel"),
                    webpage_url=video.get("url"), stages=stages, elapsed_ms=_elapsed(started),
                )

            record(IngestStage.METADATA)
            metadata = self._metadata.fetch_metadata(url)
            if playlist_id and not metadata.playlist_id:
                metadata.playlist_id = playlist_id
            if playlist_title and not metadata.playlist_title:
                metadata.playlist_title = playlist_title

            yt_memory = self._build_youtube_memory(
                owner_id=owner_id, metadata=metadata,
                playback_position_sec=playback_position_sec,
                user_notes=user_notes, status=ProcessingStatus.METADATA,
            )
            dupe = self._dupes.check_memory(yt_memory, user_id=owner_id)
            if dupe.is_duplicate and not force_refresh:
                yt_memory.is_duplicate = True
                yt_memory.duplicate_of = dupe.duplicate_of
                yt_memory.processing_status = ProcessingStatus.COMPLETED
                self._yt_store.upsert(yt_memory)
                record(IngestStage.SKIPPED, dupe.reason)
                return IngestResultItem(
                    url=url, success=True, skipped=True, video_id=metadata.video_id,
                    title=metadata.title, channel=metadata.channel,
                    webpage_url=metadata.webpage_url, stages=stages, elapsed_ms=_elapsed(started),
                )
            self._yt_store.upsert(yt_memory)

            record(IngestStage.TRANSCRIPT)
            try:
                availability = self._transcript.detect_availability(url)
                if isinstance(availability, TranscriptAvailability):
                    yt_memory.transcript_availability = availability
                transcript = _fetch_transcript_cached(url, self._transcript)
                self._yt_store.bump_metric("transcript_success", 1, user_id=owner_id)
                yt_memory.transcript_status = "retrieved"
                yt_memory.transcript_availability = TranscriptAvailability.AVAILABLE
                yt_memory.transcript_kind = (
                    TranscriptKind.AUTO_GENERATED if transcript.is_generated else TranscriptKind.MANUAL
                )
                yt_memory.language = transcript.language or metadata.language
            except AppError as exc:
                self._yt_store.bump_metric("transcript_failure", 1, user_id=owner_id)
                yt_memory.transcript_status = "failed"
                yt_memory.transcript_availability = TranscriptAvailability.UNAVAILABLE
                yt_memory.processing_status = ProcessingStatus.FAILED
                yt_memory.updated_at = _iso_now()
                self._yt_store.upsert(yt_memory)
                msg = str(exc)
                if "Failed to fetch" in msg or "Unexpected" in msg:
                    self._yt_store.enqueue_retry(
                        user_id=owner_id, url=url, external_id=metadata.video_id,
                        payload={"url": url, "force_refresh": force_refresh}, error=msg,
                    )
                    record(IngestStage.RETRY, msg)
                else:
                    record(IngestStage.FAILED, msg)
                return IngestResultItem(
                    url=url, success=False, video_id=metadata.video_id, title=metadata.title,
                    channel=metadata.channel, error=msg, stages=stages, elapsed_ms=_elapsed(started),
                )

            transcript_hash = hash_text(transcript.full_text)
            if not force_refresh and _transcript_unchanged(self._settings, video_id, transcript_hash):
                record(IngestStage.SKIPPED, "Transcript unchanged")
                video = self._registry.get_video(video_id) or {}
                self._memory_os.mark_existing_indexed(
                    user_id=owner_id, source_type=SourceType.YOUTUBE, external_id=video_id,
                    canonical_url=video.get("url") or url, title=video.get("title") or video_id,
                    source_author=video.get("channel") or "",
                )
                yt_memory.processing_status = ProcessingStatus.COMPLETED
                yt_memory.updated_at = _iso_now()
                self._yt_store.upsert(yt_memory)
                return IngestResultItem(
                    url=url, success=True, skipped=True, video_id=video_id,
                    title=video.get("title"), channel=video.get("channel"),
                    webpage_url=video.get("url"), stages=stages, elapsed_ms=_elapsed(started),
                )

            record(IngestStage.CAPSULE)
            capsule = build_capsule_with_optional_llm(
                metadata=metadata, transcript=transcript, reflection=reflection,
            )

            record(IngestStage.CHUNKING)
            yt_memory.processing_status = ProcessingStatus.CHUNKING
            self._yt_store.upsert(yt_memory)
            chunks = chunk_transcript(
                transcript.segments,
                chunk_size=self._settings.chunk_size,
                chunk_overlap=self._settings.chunk_overlap,
            )
            if not chunks:
                record(IngestStage.FAILED, "Empty transcript")
                yt_memory.processing_status = ProcessingStatus.FAILED
                yt_memory.transcript_status = "empty"
                self._yt_store.upsert(yt_memory)
                return IngestResultItem(
                    url=url, success=False, video_id=metadata.video_id,
                    error="Transcript is empty — nothing to store.",
                    stages=stages, elapsed_ms=_elapsed(started),
                )

            unique_texts, _dedup_report = dedupe_chunk_texts([c.text for c in chunks])
            remaining = set(unique_texts)
            filtered_chunks = []
            for chunk in chunks:
                if chunk.text in remaining:
                    filtered_chunks.append(chunk)
                    remaining.discard(chunk.text)
            chunks = filtered_chunks
            chunk_texts = [c.text for c in chunks]

            record(IngestStage.EMBEDDING)
            yt_memory.processing_status = ProcessingStatus.EMBEDDING
            yt_memory.embedding_status = "processing"
            self._yt_store.upsert(yt_memory)
            try:
                batch_size = self._settings.embedding_batch_size
                all_embeddings: list[list[float]] = []
                for i in range(0, len(chunk_texts), batch_size):
                    batch = chunk_texts[i : i + batch_size]
                    all_embeddings.extend(embed_texts(batch, settings=self._settings))
                capsule_emb = embed_texts(
                    [capsule.short_summary or capsule.one_line_memory], settings=self._settings
                )[0]
                section_texts = [f"{s.title}. {s.summary}" for s in capsule.sections] or [capsule.short_summary]
                section_embs = embed_texts(section_texts, settings=self._settings)
            except Exception as exc:
                self._yt_store.bump_metric("embedding_failures", 1, user_id=owner_id)
                yt_memory.embedding_status = "failed"
                yt_memory.processing_status = ProcessingStatus.FAILED
                self._yt_store.upsert(yt_memory)
                raise AppError(f"Embedding failed: {exc}") from exc

            transcript_source = "auto_generated" if transcript.is_generated else "manual_captions"
            enrichment = enrich_video(
                title=metadata.title, description=metadata.description, channel=metadata.channel,
                transcript_text=transcript.full_text, chunk_texts=[chunk.text for chunk in chunks],
            )

            record(IngestStage.STORING)
            self._hstore.delete_video(metadata.video_id)
            self._fts.delete_video(metadata.video_id, user_id=owner_id)
            chunk_count = self._repository.upsert_chunks(
                video_id=metadata.video_id, user_id=owner_id, url=metadata.webpage_url,
                title=metadata.title, channel=metadata.channel, thumbnail=metadata.thumbnail,
                duration=metadata.duration, transcript_source=transcript_source, chunks=chunks,
                embeddings=all_embeddings, embedding_model=self._settings.embedding_model,
                description=metadata.description, one_line_memory=enrichment.one_line_memory,
                why_saved=_merge_why_saved(enrichment.why_saved, reflection),
                action_items=enrichment.action_items, language=yt_memory.language,
                channel_id=metadata.channel_id, published_at=metadata.published_at,
                tags=metadata.tags, categories=metadata.categories, playlist_id=metadata.playlist_id,
            )

            if self._settings.hierarchical_retrieval_enabled:
                self._hstore.upsert_capsule(capsule, capsule_emb)
                if capsule.sections:
                    self._hstore.upsert_sections(metadata.video_id, capsule.sections, section_embs)
                store_capsule_json(self._settings, metadata.video_id, capsule)
                self._fts.upsert(
                    video_id=metadata.video_id, level="capsule",
                    doc_id=f"capsule_{metadata.video_id}", title=capsule.title,
                    body=f"{capsule.short_summary} {' '.join(capsule.topics)}",
                    user_id=owner_id,
                )
                for idx, section in enumerate(capsule.sections):
                    self._fts.upsert(
                        video_id=metadata.video_id, level="section",
                        doc_id=f"section_{metadata.video_id}_{idx}",
                        title=section.title, body=section.summary,
                        user_id=owner_id,
                    )
                for chunk in chunks:
                    self._fts.upsert(
                        video_id=metadata.video_id, level="evidence",
                        doc_id=f"youtube_{metadata.video_id}_{chunk.chunk_index}",
                        title=metadata.title, body=chunk.text,
                        user_id=owner_id,
                    )

            _store_transcript_hash(self._settings, metadata.video_id, transcript_hash)
            SemanticCache(self._settings).bump_index_version_and_invalidate()

            self._registry.upsert_video(
                video_id=metadata.video_id, user_id=owner_id, url=metadata.webpage_url,
                title=metadata.title, channel=metadata.channel, reflection=reflection,
            )
            self._memory_os.finalize_ingest(
                user_id=owner_id, metadata=metadata, capsule=capsule, reflection=reflection,
                chunk_count=chunk_count, embedding_model=self._settings.embedding_model,
                transcript_source=transcript_source,
                has_capsule=self._settings.hierarchical_retrieval_enabled,
            )

            record(IngestStage.INDEXED, f"{chunk_count} chunks")
            yt_memory.chunk_count = chunk_count
            yt_memory.embedding_status = "completed"
            yt_memory.processing_status = ProcessingStatus.INDEXED
            yt_memory.updated_at = _iso_now()
            self._yt_store.upsert(yt_memory)

            record(IngestStage.COMPLETED, f"{chunk_count} chunks")
            yt_memory.processing_status = ProcessingStatus.COMPLETED
            yt_memory.updated_at = _iso_now()
            self._yt_store.upsert(yt_memory)
            self._yt_store.bump_metric("videos_saved", 1, user_id=owner_id)
            self._yt_store.bump_metric(
                "average_indexing_ms", _elapsed(started) or 0.0,
                user_id=owner_id, as_average=True,
            )
            try:
                from app.services.cross_duplicate_service import CrossConnectorDuplicateDetector

                CrossConnectorDuplicateDetector(self._settings).register(
                    user_id=owner_id,
                    canonical_url=metadata.webpage_url,
                    content_hash=metadata.content_hash or "",
                    source_type=SourceType.YOUTUBE.value,
                    connector_id=metadata.connector_id or "youtube.v1",
                    external_id=metadata.video_id,
                )
            except Exception:
                pass

            return IngestResultItem(
                url=url, success=True, video_id=metadata.video_id, title=metadata.title,
                channel=metadata.channel, thumbnail=metadata.thumbnail, duration=metadata.duration,
                webpage_url=metadata.webpage_url, chunk_count=chunk_count,
                transcript_source=transcript_source, stages=stages, elapsed_ms=_elapsed(started),
            )
        except InvalidYouTubeURLError as exc:
            record(IngestStage.FAILED, exc.message)
            return IngestResultItem(
                url=url, success=False, error=exc.message, stages=stages, elapsed_ms=_elapsed(started),
            )
        except AppError as exc:
            record(IngestStage.FAILED, exc.message)
            return IngestResultItem(
                url=url, success=False, error=exc.message, stages=stages, elapsed_ms=_elapsed(started),
            )
        except Exception as exc:
            record(IngestStage.FAILED, str(exc))
            return IngestResultItem(
                url=url, success=False, error=f"Unexpected error: {exc}",
                stages=stages, elapsed_ms=_elapsed(started),
            )

    def _build_youtube_memory(
        self, *, owner_id: str, metadata, playback_position_sec: float | None,
        user_notes: str, status: ProcessingStatus,
    ) -> YouTubeMemory:
        now = _iso_now()
        existing = self._yt_store.get(metadata.video_id, user_id=owner_id)
        return YouTubeMemory(
            memory_id=existing.memory_id if existing else new_memory_id(),
            user_id=owner_id,
            video_id=metadata.video_id,
            url=metadata.webpage_url,
            title=metadata.title,
            description=metadata.description or "",
            channel=metadata.channel or "",
            channel_id=metadata.channel_id or "",
            published_at=metadata.published_at,
            duration_sec=metadata.duration,
            thumbnail=metadata.thumbnail or "",
            playback_position_sec=playback_position_sec,
            language=metadata.language,
            tags=list(metadata.tags or []),
            categories=list(metadata.categories or []),
            playlist_id=metadata.playlist_id,
            playlist_title=metadata.playlist_title,
            playlist_index=metadata.playlist_index,
            saved_at=existing.saved_at if existing else now,
            user_notes=user_notes or (existing.user_notes if existing else ""),
            processing_status=status,
            content_hash=metadata.content_hash or "",
            raw_metadata=dict(metadata.raw_metadata or {}),
            updated_at=now,
            connector_id=metadata.connector_id or "youtube.v1",
        )


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dedupe_urls(urls: list[str]) -> list[str]:
    seen_ids: set[str] = set()
    deduped: list[str] = []
    for raw in urls:
        url = raw.strip()
        if not url:
            continue
        try:
            parsed = parse_youtube_url(url)
            if parsed.video_id in seen_ids:
                continue
            seen_ids.add(parsed.video_id)
        except InvalidYouTubeURLError:
            pass
        deduped.append(url)
    return deduped


def _fetch_transcript_cached(url: str, service: TranscriptService):
    try:
        parsed = parse_youtube_url(url)
        cache_key = parsed.video_id
    except InvalidYouTubeURLError:
        cache_key = url

    if cache_key in _TRANSCRIPT_CACHE:
        return _TRANSCRIPT_CACHE[cache_key]

    transcript = service.fetch_transcript(url)
    _TRANSCRIPT_CACHE[cache_key] = transcript
    return transcript


def _merge_why_saved(existing: list[str], reflection: ReflectionInput | None) -> list[str]:
    merged = list(existing)
    if reflection and reflection.reflection_note:
        note = f"You saved this because: {reflection.reflection_note}"
        if note not in merged:
            merged.insert(0, note)
    if reflection and reflection.goal:
        goal = f"Current goal: {reflection.goal}"
        if goal not in merged:
            merged.insert(0, goal)
    return merged


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _transcript_unchanged(settings: Settings, video_id: str, transcript_hash: str) -> bool:
    migrate(settings)
    with get_connection(settings) as conn:
        row = conn.execute(
            "SELECT transcript_hash FROM content_hashes WHERE video_id = ?",
            (video_id,),
        ).fetchone()
        return bool(row and row["transcript_hash"] == transcript_hash)


def _store_transcript_hash(settings: Settings, video_id: str, transcript_hash: str) -> None:
    from datetime import datetime, timezone

    migrate(settings)
    with get_connection(settings) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO content_hashes (video_id, transcript_hash, normalized_path, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (video_id, transcript_hash, "", datetime.now(timezone.utc).isoformat()),
        )