"""Tenant-scoped Postgres persistence for YouTube memory and operational state.

P-03 moves production relational state in test-gated slices. This store keeps
core YouTube memories, pipeline telemetry, retry/dead-letter state, and
connector diagnostics on one Postgres boundary with explicit tenant identity.
Runtime backend routing and SQLite migration remain separate acceptance slices.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db.postgres_job_repository import ConnectionFactory
from app.models.youtube_memory import YouTubeDiagnostics, YouTubeMemory
from app.services.sources.base_source import ProcessingStatus
from app.services.sources.youtube_connector import CONNECTOR_ID


def ensure_postgres_youtube_memory_schema(connection_factory: ConnectionFactory) -> None:
    """Create tenant-scoped YouTube memory and operational tables idempotently."""
    with connection_factory() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS youtube_memories (
                memory_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                video_id TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '',
                channel_id TEXT NOT NULL DEFAULT '',
                published_at TEXT,
                duration_sec DOUBLE PRECISION,
                thumbnail TEXT NOT NULL DEFAULT '',
                playback_position_sec DOUBLE PRECISION,
                language TEXT,
                transcript_availability TEXT NOT NULL,
                transcript_kind TEXT NOT NULL,
                transcript_status TEXT NOT NULL DEFAULT 'pending',
                tags_json TEXT NOT NULL DEFAULT '[]',
                categories_json TEXT NOT NULL DEFAULT '[]',
                playlist_id TEXT,
                playlist_title TEXT,
                playlist_index INTEGER,
                saved_at TEXT NOT NULL,
                user_notes TEXT NOT NULL DEFAULT '',
                embedding_status TEXT NOT NULL DEFAULT 'pending',
                processing_status TEXT NOT NULL DEFAULT 'queued',
                content_hash TEXT NOT NULL DEFAULT '',
                chunk_count INTEGER NOT NULL DEFAULT 0,
                duplicate_of TEXT,
                is_duplicate BOOLEAN NOT NULL DEFAULT FALSE,
                raw_metadata_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, video_id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_youtube_memories_tenant_hash
            ON youtube_memories(user_id, content_hash)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_youtube_memories_tenant_saved
            ON youtube_memories(user_id, saved_at DESC)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS youtube_pipeline_runs (
                id BIGSERIAL PRIMARY KEY,
                run_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                video_id TEXT NOT NULL DEFAULT '',
                capture_id TEXT,
                stage TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                elapsed_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_youtube_pipeline_tenant_run
            ON youtube_pipeline_runs(user_id, run_id, id)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS youtube_retry_queue (
                id BIGSERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                connector_id TEXT NOT NULL,
                external_id TEXT NOT NULL,
                url TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 5,
                next_attempt_at TEXT NOT NULL,
                last_error TEXT NOT NULL DEFAULT '',
                dead_lettered BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, connector_id, external_id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_youtube_retry_tenant_due
            ON youtube_retry_queue(user_id, connector_id, dead_lettered, next_attempt_at)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS youtube_connector_metrics (
                user_id TEXT NOT NULL,
                metric_key TEXT NOT NULL,
                connector_id TEXT NOT NULL,
                value_real DOUBLE PRECISION NOT NULL DEFAULT 0,
                value_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, metric_key, connector_id)
            )
            """
        )


class PostgresYouTubeMemoryStore:
    """Tenant-scoped CRUD and operational state for the YouTube connector."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connect = connection_factory
        ensure_postgres_youtube_memory_schema(connection_factory)

    def upsert(self, memory: YouTubeMemory) -> YouTubeMemory:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO youtube_memories (
                    memory_id, user_id, video_id, url, title, description, channel, channel_id,
                    published_at, duration_sec, thumbnail, playback_position_sec, language,
                    transcript_availability, transcript_kind, transcript_status,
                    tags_json, categories_json, playlist_id, playlist_title, playlist_index,
                    saved_at, user_notes, embedding_status, processing_status, content_hash,
                    chunk_count, duplicate_of, is_duplicate, raw_metadata_json, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT(user_id, video_id) DO UPDATE SET
                    memory_id = EXCLUDED.memory_id,
                    url = EXCLUDED.url,
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    channel = EXCLUDED.channel,
                    channel_id = EXCLUDED.channel_id,
                    published_at = EXCLUDED.published_at,
                    duration_sec = EXCLUDED.duration_sec,
                    thumbnail = EXCLUDED.thumbnail,
                    playback_position_sec = EXCLUDED.playback_position_sec,
                    language = EXCLUDED.language,
                    transcript_availability = EXCLUDED.transcript_availability,
                    transcript_kind = EXCLUDED.transcript_kind,
                    transcript_status = EXCLUDED.transcript_status,
                    tags_json = EXCLUDED.tags_json,
                    categories_json = EXCLUDED.categories_json,
                    playlist_id = EXCLUDED.playlist_id,
                    playlist_title = EXCLUDED.playlist_title,
                    playlist_index = EXCLUDED.playlist_index,
                    user_notes = EXCLUDED.user_notes,
                    embedding_status = EXCLUDED.embedding_status,
                    processing_status = EXCLUDED.processing_status,
                    content_hash = EXCLUDED.content_hash,
                    chunk_count = EXCLUDED.chunk_count,
                    duplicate_of = EXCLUDED.duplicate_of,
                    is_duplicate = EXCLUDED.is_duplicate,
                    raw_metadata_json = EXCLUDED.raw_metadata_json,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    memory.memory_id, memory.user_id, memory.video_id, memory.url, memory.title,
                    memory.description, memory.channel, memory.channel_id, memory.published_at,
                    memory.duration_sec, memory.thumbnail, memory.playback_position_sec,
                    memory.language, memory.transcript_availability.value, memory.transcript_kind.value,
                    memory.transcript_status, json.dumps(memory.tags), json.dumps(memory.categories),
                    memory.playlist_id, memory.playlist_title, memory.playlist_index, memory.saved_at,
                    memory.user_notes, memory.embedding_status, memory.processing_status.value,
                    memory.content_hash, memory.chunk_count, memory.duplicate_of, bool(memory.is_duplicate),
                    json.dumps(memory.raw_metadata), memory.updated_at,
                ),
            )
        return memory

    def get(self, video_id: str, *, user_id: str) -> YouTubeMemory | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM youtube_memories WHERE user_id = %s AND video_id = %s",
                (user_id, video_id),
            ).fetchone()
        return _row_to_memory(row) if row else None

    def get_by_content_hash(self, content_hash: str, *, user_id: str) -> YouTubeMemory | None:
        if not content_hash:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM youtube_memories
                WHERE user_id = %s AND content_hash = %s AND is_duplicate = FALSE
                ORDER BY saved_at ASC LIMIT 1
                """,
                (user_id, content_hash),
            ).fetchone()
        return _row_to_memory(row) if row else None

    def list_for_user(self, user_id: str, *, limit: int = 200) -> list[YouTubeMemory]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM youtube_memories
                WHERE user_id = %s ORDER BY saved_at DESC LIMIT %s
                """,
                (user_id, limit),
            ).fetchall()
        return [_row_to_memory(row) for row in rows]

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
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO youtube_pipeline_runs (
                    run_id, user_id, video_id, capture_id, stage, detail, elapsed_ms, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (run_id, user_id, video_id, capture_id, stage, detail, elapsed_ms, _utc_now()),
            )

    def list_pipeline_stages(self, run_id: str, *, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT stage, detail, elapsed_ms, created_at FROM youtube_pipeline_runs
                WHERE user_id = %s AND run_id = %s ORDER BY id
                """,
                (user_id, run_id),
            ).fetchall()
        return [dict(row) for row in rows]

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
        next_at = (now + timedelta(seconds=min(300, 2**attempt_count))).isoformat()
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT id, attempt_count FROM youtube_retry_queue
                WHERE user_id = %s AND connector_id = %s AND external_id = %s
                  AND dead_lettered = FALSE
                """,
                (user_id, CONNECTOR_ID, external_id),
            ).fetchone()
            if existing:
                attempts = int(existing["attempt_count"]) + 1
                conn.execute(
                    """
                    UPDATE youtube_retry_queue
                    SET attempt_count = %s, next_attempt_at = %s, last_error = %s,
                        dead_lettered = %s, updated_at = %s, payload_json = %s, url = %s
                    WHERE id = %s AND user_id = %s
                    """,
                    (
                        attempts, next_at, error[:2000], attempts >= max_attempts,
                        now.isoformat(), json.dumps(payload), url, existing["id"], user_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO youtube_retry_queue (
                        user_id, connector_id, external_id, url, payload_json,
                        attempt_count, max_attempts, next_attempt_at, last_error,
                        dead_lettered, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s, %s)
                    ON CONFLICT(user_id, connector_id, external_id) DO NOTHING
                    """,
                    (
                        user_id, CONNECTOR_ID, external_id, url, json.dumps(payload),
                        max(1, attempt_count), max_attempts, next_at, error[:2000],
                        now.isoformat(), now.isoformat(),
                    ),
                )
        self.bump_metric("retry_count", 1, user_id=user_id)

    def claim_due_retries(self, *, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM youtube_retry_queue
                WHERE user_id = %s AND connector_id = %s AND dead_lettered = FALSE
                  AND next_attempt_at <= %s
                ORDER BY next_attempt_at ASC, id ASC LIMIT %s
                """,
                (user_id, CONNECTOR_ID, _utc_now(), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def bump_metric(
        self,
        key: str,
        amount: float = 1.0,
        *,
        user_id: str,
        as_average: bool = False,
    ) -> None:
        now = _utc_now()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT value_real, value_count FROM youtube_connector_metrics
                WHERE user_id = %s AND metric_key = %s AND connector_id = %s
                """,
                (user_id, key, CONNECTOR_ID),
            ).fetchone()
            if not row:
                conn.execute(
                    """
                    INSERT INTO youtube_connector_metrics (
                        user_id, metric_key, connector_id, value_real, value_count, updated_at
                    ) VALUES (%s, %s, %s, %s, 1, %s)
                    """,
                    (user_id, key, CONNECTOR_ID, amount, now),
                )
                return
            old_count = int(row["value_count"])
            count = old_count + 1
            if as_average:
                new_val = ((float(row["value_real"]) * old_count) + amount) / count
            else:
                new_val = float(row["value_real"]) + amount
                count = old_count + int(amount if amount >= 1 else 1)
            conn.execute(
                """
                UPDATE youtube_connector_metrics
                SET value_real = %s, value_count = %s, updated_at = %s
                WHERE user_id = %s AND metric_key = %s AND connector_id = %s
                """,
                (new_val, count, now, user_id, key, CONNECTOR_ID),
            )

    def record_search_latency(self, ms: float, *, user_id: str) -> None:
        self.bump_metric("average_search_latency_ms", ms, user_id=user_id, as_average=True)

    def diagnostics(self, *, user_id: str) -> YouTubeDiagnostics:
        with self._connect() as conn:
            saved = conn.execute(
                "SELECT COUNT(*) AS c FROM youtube_memories WHERE user_id = %s", (user_id,)
            ).fetchone()["c"]
            pending = conn.execute(
                """
                SELECT COUNT(*) AS c FROM youtube_retry_queue
                WHERE user_id = %s AND connector_id = %s AND dead_lettered = FALSE
                """,
                (user_id, CONNECTOR_ID),
            ).fetchone()["c"]
            dead = conn.execute(
                """
                SELECT COUNT(*) AS c FROM youtube_retry_queue
                WHERE user_id = %s AND connector_id = %s AND dead_lettered = TRUE
                """,
                (user_id, CONNECTOR_ID),
            ).fetchone()["c"]
            metrics = {
                row["metric_key"]: dict(row)
                for row in conn.execute(
                    """
                    SELECT metric_key, value_real, value_count FROM youtube_connector_metrics
                    WHERE user_id = %s AND connector_id = %s
                    """,
                    (user_id, CONNECTOR_ID),
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
            average_indexing_ms=float(metrics.get("average_indexing_ms", {}).get("value_real", 0) or 0),
            average_search_latency_ms=float(
                metrics.get("average_search_latency_ms", {}).get("value_real", 0) or 0
            ),
            pending_retries=int(pending),
        )


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
