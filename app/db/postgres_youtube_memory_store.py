"""Tenant-scoped Postgres persistence for core YouTube memory records.

P-03 moves production relational state in test-gated slices.  This primitive
covers the durable YouTube memory/duplicate metadata first; pipeline telemetry,
retry state, metrics, and runtime routing remain separate slices so they are not
silently split between backends.
"""

from __future__ import annotations

import json
from typing import Any

from app.db.postgres_job_repository import ConnectionFactory
from app.models.youtube_memory import YouTubeMemory
from app.services.sources.base_source import ProcessingStatus


def ensure_postgres_youtube_memory_schema(connection_factory: ConnectionFactory) -> None:
    """Create the tenant-scoped YouTube memory table idempotently."""
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


class PostgresYouTubeMemoryStore:
    """Core CRUD parity for the tenant-scoped SQLite YouTube memory records."""

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
                    bool(memory.is_duplicate),
                    json.dumps(memory.raw_metadata),
                    memory.updated_at,
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
