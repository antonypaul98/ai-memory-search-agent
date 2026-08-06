"""Persistence for YouTube Memory records, pipeline runs, retries, metrics."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import Settings, get_settings
from app.db.schema import get_connection, migrate
from app.models.youtube_memory import YouTubeDiagnostics, YouTubeMemory
from app.services.sources.base_source import ProcessingStatus
from app.services.sources.youtube_connector import CONNECTOR_ID


class YouTubeMemoryStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        migrate(self._settings)

    def upsert(self, memory: YouTubeMemory) -> YouTubeMemory:
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT INTO youtube_memories (
                    memory_id, user_id, video_id, url, title, description, channel, channel_id,
                    published_at, duration_sec, thumbnail, playback_position_sec, language,
                    transcript_availability, transcript_kind, transcript_status,
                    tags_json, categories_json, playlist_id, playlist_title, playlist_index,
                    saved_at, user_notes, embedding_status, processing_status, content_hash,
                    chunk_count, duplicate_of, is_duplicate, raw_metadata_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, video_id) DO UPDATE SET
                    memory_id = excluded.memory_id,
                    url = excluded.url,
                    title = excluded.title,
                    description = excluded.description,
                    channel = excluded.channel,
                    channel_id = excluded.channel_id,
                    published_at = excluded.published_at,
                    duration_sec = excluded.duration_sec,
                    thumbnail = excluded.thumbnail,
                    playback_position_sec = excluded.playback_position_sec,
                    language = excluded.language,
                    transcript_availability = excluded.transcript_availability,
                    transcript_kind = excluded.transcript_kind,
                    transcript_status = excluded.transcript_status,
                    tags_json = excluded.tags_json,
                    categories_json = excluded.categories_json,
                    playlist_id = excluded.playlist_id,
                    playlist_title = excluded.playlist_title,
                    playlist_index = excluded.playlist_index,
                    user_notes = excluded.user_notes,
                    embedding_status = excluded.embedding_status,
                    processing_status = excluded.processing_status,
                    content_hash = excluded.content_hash,
                    chunk_count = excluded.chunk_count,
                    duplicate_of = excluded.duplicate_of,
                    is_duplicate = excluded.is_duplicate,
                    raw_metadata_json = excluded.raw_metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    memory.memory_id,
                    memory.user_id,
                    memory.video_id,
                    memory.url,
                    memory.title,
                    memory.description,
                    memory.channel,
                    memory.channel_id,
                    memory.published_at,
                    memory.duration_sec,
                    memory.thumbnail,
                    memory.playback_position_sec,
                    memory.language,
                    memory.transcript_availability.value,
                    memory.transcript_kind.value,
                    memory.transcript_status,
                    json.dumps(memory.tags),
                    json.dumps(memory.categories),
                    memory.playlist_id,
                    memory.playlist_title,
                    memory.playlist_index,
                    memory.saved_at,
                    memory.user_notes,
                    memory.embedding_status,
                    memory.processing_status.value,
                    memory.content_hash,
                    memory.chunk_count,
                    memory.duplicate_of,
                    1 if memory.is_duplicate else 0,
                    json.dumps(memory.raw_metadata),
                    memory.updated_at,
                ),
            )
        return memory

    def get(self, video_id: str, *, user_id: str) -> YouTubeMemory | None:
        with get_connection(self._settings) as conn:
            row = conn.execute(
                "SELECT * FROM youtube_memories WHERE user_id = ? AND video_id = ?",
                (user_id, video_id),
            ).fetchone()
        return _row_to_memory(row) if row else None

    def get_by_content_hash(self, content_hash: str, *, user_id: str) -> YouTubeMemory | None:
        if not content_hash:
            return None
        with get_connection(self._settings) as conn:
            row = conn.execute(
                """
                SELECT * FROM youtube_memories
                WHERE user_id = ? AND content_hash = ? AND is_duplicate = 0
                ORDER BY saved_at ASC LIMIT 1
                """,
                (user_id, content_hash),
            ).fetchone()
        return _row_to_memory(row) if row else None

    def list_for_user(self, user_id: str, *, limit: int = 200) -> list[YouTubeMemory]:
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                """
                SELECT * FROM youtube_memories WHERE user_id = ?
                ORDER BY saved_at DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [_row_to_memory(r) for r in rows]

    def record_pipeline_stage(
        self,
        *,
        run_id: str,
        user_id: str,
        video_id: str = "",
        capture_id: str | None = None,
        stage: str,
        detail: str = "",
        elapsed_ms: float = 0.0,
    ) -> None:
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT INTO pipeline_runs (
                    run_id, user_id, video_id, capture_id, stage, detail, elapsed_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    user_id,
                    video_id,
                    capture_id,
                    stage,
                    detail,
                    elapsed_ms,
                    _utc_now(),
                ),
            )

    def list_pipeline_stages(self, run_id: str) -> list[dict[str, Any]]:
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                """
                SELECT stage, detail, elapsed_ms, created_at FROM pipeline_runs
                WHERE run_id = ? ORDER BY id
                """,
                (run_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def enqueue_retry(
        self,
        *,
        user_id: str,
        url: str,
        external_id: str,
        payload: dict[str, Any],
        error: str,
        attempt_count: int = 0,
        max_attempts: int = 5,
    ) -> None:
        now = datetime.now(timezone.utc)
        delay = min(300, 2**attempt_count)
        next_at = (now + timedelta(seconds=delay)).isoformat()
        with get_connection(self._settings) as conn:
            existing = conn.execute(
                """
                SELECT id, attempt_count FROM connector_retry_queue
                WHERE user_id = ? AND connector_id = ? AND external_id = ? AND dead_lettered = 0
                """,
                (user_id, CONNECTOR_ID, external_id),
            ).fetchone()
            if existing:
                attempts = int(existing["attempt_count"]) + 1
                dead = 1 if attempts >= max_attempts else 0
                conn.execute(
                    """
                    UPDATE connector_retry_queue
                    SET attempt_count = ?, next_attempt_at = ?, last_error = ?,
                        dead_lettered = ?, updated_at = ?, payload_json = ?, url = ?
                    WHERE id = ?
                    """,
                    (
                        attempts,
                        next_at,
                        error[:2000],
                        dead,
                        now.isoformat(),
                        json.dumps(payload),
                        url,
                        existing["id"],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO connector_retry_queue (
                        user_id, connector_id, external_id, url, payload_json,
                        attempt_count, max_attempts, next_attempt_at, last_error,
                        dead_lettered, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        user_id,
                        CONNECTOR_ID,
                        external_id,
                        url,
                        json.dumps(payload),
                        max(1, attempt_count),
                        max_attempts,
                        next_at,
                        error[:2000],
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
        self.bump_metric("retry_count", 1)

    def claim_due_retries(self, *, limit: int = 10) -> list[dict[str, Any]]:
        now = _utc_now()
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                """
                SELECT * FROM connector_retry_queue
                WHERE dead_lettered = 0 AND next_attempt_at <= ?
                ORDER BY next_attempt_at ASC LIMIT ?
                """,
                (now, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def bump_metric(self, key: str, amount: float = 1.0, *, as_average: bool = False) -> None:
        now = _utc_now()
        with get_connection(self._settings) as conn:
            row = conn.execute(
                "SELECT value_real, value_count FROM connector_metrics WHERE metric_key = ? AND connector_id = ?",
                (key, CONNECTOR_ID),
            ).fetchone()
            if not row:
                conn.execute(
                    """
                    INSERT INTO connector_metrics (metric_key, connector_id, value_real, value_count, updated_at)
                    VALUES (?, ?, ?, 1, ?)
                    """,
                    (key, CONNECTOR_ID, amount, now),
                )
                return
            count = int(row["value_count"]) + 1
            if as_average:
                new_val = ((float(row["value_real"]) * int(row["value_count"])) + amount) / count
            else:
                new_val = float(row["value_real"]) + amount
                count = int(row["value_count"]) + int(amount if amount >= 1 else 1)
            conn.execute(
                """
                UPDATE connector_metrics
                SET value_real = ?, value_count = ?, updated_at = ?
                WHERE metric_key = ? AND connector_id = ?
                """,
                (new_val, count, now, key, CONNECTOR_ID),
            )

    def record_search_latency(self, ms: float) -> None:
        self.bump_metric("average_search_latency_ms", ms, as_average=True)

    def diagnostics(self) -> YouTubeDiagnostics:
        with get_connection(self._settings) as conn:
            saved = conn.execute("SELECT COUNT(*) AS c FROM youtube_memories").fetchone()["c"]
            pending = conn.execute(
                "SELECT COUNT(*) AS c FROM connector_retry_queue WHERE dead_lettered = 0"
            ).fetchone()["c"]
            dead = conn.execute(
                "SELECT COUNT(*) AS c FROM connector_retry_queue WHERE dead_lettered = 1"
            ).fetchone()["c"]
            metrics = {
                r["metric_key"]: dict(r)
                for r in conn.execute(
                    "SELECT metric_key, value_real, value_count FROM connector_metrics WHERE connector_id = ?",
                    (CONNECTOR_ID,),
                ).fetchall()
            }
        tx_ok = float(metrics.get("transcript_success", {}).get("value_real", 0) or 0)
        tx_fail = float(metrics.get("transcript_failure", {}).get("value_real", 0) or 0)
        total_tx = tx_ok + tx_fail
        rate = (tx_ok / total_tx) if total_tx else 0.0
        return YouTubeDiagnostics(
            healthy=True,
            videos_saved=int(saved),
            transcript_success=int(tx_ok),
            transcript_failure=int(tx_fail),
            transcript_success_rate=round(rate, 4),
            embedding_failures=int(metrics.get("embedding_failures", {}).get("value_real", 0) or 0),
            retry_count=int(metrics.get("retry_count", {}).get("value_real", 0) or 0),
            dead_letter_count=int(dead),
            average_indexing_ms=float(
                metrics.get("average_indexing_ms", {}).get("value_real", 0) or 0
            ),
            average_search_latency_ms=float(
                metrics.get("average_search_latency_ms", {}).get("value_real", 0) or 0
            ),
            pending_retries=int(pending),
        )


def new_memory_id() -> str:
    return str(uuid.uuid4())


def _row_to_memory(row: Any) -> YouTubeMemory:
    return YouTubeMemory(
        memory_id=row["memory_id"],
        user_id=row["user_id"],
        video_id=row["video_id"],
        url=row["url"],
        title=row["title"],
        description=row["description"] or "",
        channel=row["channel"] or "",
        channel_id=row["channel_id"] or "",
        published_at=row["published_at"],
        duration_sec=row["duration_sec"],
        thumbnail=row["thumbnail"] or "",
        playback_position_sec=row["playback_position_sec"],
        language=row["language"],
        transcript_availability=row["transcript_availability"],
        transcript_kind=row["transcript_kind"],
        transcript_status=row["transcript_status"] or "pending",
        tags=json.loads(row["tags_json"] or "[]"),
        categories=json.loads(row["categories_json"] or "[]"),
        playlist_id=row["playlist_id"],
        playlist_title=row["playlist_title"],
        playlist_index=row["playlist_index"],
        saved_at=row["saved_at"],
        user_notes=row["user_notes"] or "",
        embedding_status=row["embedding_status"] or "pending",
        processing_status=ProcessingStatus(row["processing_status"] or "queued"),
        content_hash=row["content_hash"] or "",
        chunk_count=int(row["chunk_count"] or 0),
        duplicate_of=row["duplicate_of"],
        is_duplicate=bool(row["is_duplicate"]),
        raw_metadata=json.loads(row["raw_metadata_json"] or "{}"),
        updated_at=row["updated_at"],
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
