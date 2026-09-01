"""Safe, idempotent SQLite -> Postgres migration for YouTube state.

The legacy SQLite source is opened read-only and consumed from one snapshot.
Target rows are insert-only: existing Postgres business state remains
authoritative. Pipeline history has no natural target uniqueness key, so a
count-free migration ledger stores a deterministic hash of each legacy source
row (including its SQLite surrogate id) before inserting that event.

Legacy ``connector_metrics`` are global rather than tenant-scoped. They are
therefore migrated only when the source has exactly one identifiable tenant;
ambiguous attribution fails before any Postgres writes instead of guessing.
Reports expose counts/booleans only and never include URLs, payloads, errors,
DSNs, credentials, or other private row content.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.db.postgres_job_repository import ConnectionFactory
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.postgres_youtube_memory_store import ensure_postgres_youtube_memory_schema
from app.services.sources.youtube_connector import CONNECTOR_ID


@dataclass(frozen=True)
class YouTubeStateMigrationPreview:
    memories: int
    pipeline_stages: int
    retries: int
    legacy_metrics: int
    tenants: int
    metrics_attribution_safe: bool

    def to_dict(self) -> dict[str, int | bool]:
        return asdict(self)


@dataclass(frozen=True)
class YouTubeStateMigrationReport:
    memories_seen: int
    memories_inserted: int
    memories_skipped_existing: int
    pipeline_stages_seen: int
    pipeline_stages_inserted: int
    pipeline_stages_skipped_existing: int
    retries_seen: int
    retries_inserted: int
    retries_skipped_existing: int
    metrics_seen: int
    metrics_inserted: int
    metrics_skipped_existing: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def preview_youtube_state_migration(
    settings: Settings | None = None,
    *,
    user_id: str | None = None,
) -> YouTubeStateMigrationPreview:
    """Return count-only source information without contacting Postgres."""
    settings = settings or get_settings()
    user_id = _normalize_user_id(user_id)
    with _open_source_read_only(settings) as conn:
        tenant_where, tenant_params = _tenant_filter(user_id)
        memories = _count(conn, f"SELECT COUNT(*) FROM youtube_memories{tenant_where}", tenant_params)
        pipeline = _count(conn, f"SELECT COUNT(*) FROM pipeline_runs{tenant_where}", tenant_params)
        retry_where, retry_params = _retry_filter(user_id)
        retries = _count(conn, f"SELECT COUNT(*) FROM connector_retry_queue{retry_where}", retry_params)
        legacy_metrics = _count(
            conn,
            "SELECT COUNT(*) FROM connector_metrics WHERE connector_id = ?",
            (CONNECTOR_ID,),
        )
        tenant_ids = _source_tenants(conn)
        safe = _metrics_attribution_safe(tenant_ids, legacy_metrics, user_id)
    return YouTubeStateMigrationPreview(
        memories=memories,
        pipeline_stages=pipeline,
        retries=retries,
        legacy_metrics=legacy_metrics,
        tenants=len(tenant_ids),
        metrics_attribution_safe=safe,
    )


def migrate_youtube_state_to_postgres(
    settings: Settings | None = None,
    *,
    user_id: str | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> YouTubeStateMigrationReport:
    """Insert missing legacy YouTube state without overwriting target state."""
    settings = settings or get_settings()
    user_id = _normalize_user_id(user_id)

    # Validate and read the complete source snapshot before opening the target.
    # This prevents ambiguous global metrics from creating a partial migration.
    with _open_source_read_only(settings) as source:
        source.execute("BEGIN")
        tenant_ids = _source_tenants(source)
        metrics = source.execute(
            """
            SELECT metric_key, connector_id, value_real, value_count, updated_at
            FROM connector_metrics
            WHERE connector_id = ?
            ORDER BY metric_key, connector_id
            """,
            (CONNECTOR_ID,),
        ).fetchall()
        if not _metrics_attribution_safe(tenant_ids, len(metrics), user_id):
            raise ValueError(
                "Legacy YouTube connector metrics are global and cannot be safely "
                "attributed to a tenant; migrate only after the source has exactly "
                "one identifiable tenant (and select that tenant if --user-id is used)."
            )

        tenant_where, tenant_params = _tenant_filter(user_id)
        memories = source.execute(
            "SELECT memory_id, user_id, video_id, url, title, description, channel, channel_id, "
            "published_at, duration_sec, thumbnail, playback_position_sec, language, "
            "transcript_availability, transcript_kind, transcript_status, tags_json, "
            "categories_json, playlist_id, playlist_title, playlist_index, saved_at, "
            "user_notes, embedding_status, processing_status, content_hash, chunk_count, "
            "duplicate_of, is_duplicate, raw_metadata_json, updated_at "
            f"FROM youtube_memories{tenant_where} ORDER BY user_id, saved_at, video_id",
            tenant_params,
        ).fetchall()
        pipeline = source.execute(
            "SELECT id, run_id, user_id, video_id, capture_id, stage, detail, elapsed_ms, created_at "
            f"FROM pipeline_runs{tenant_where} ORDER BY user_id, run_id, id",
            tenant_params,
        ).fetchall()
        retry_where, retry_params = _retry_filter(user_id)
        retries = source.execute(
            "SELECT id, user_id, connector_id, external_id, url, payload_json, attempt_count, "
            "max_attempts, next_attempt_at, last_error, dead_lettered, created_at, updated_at "
            f"FROM connector_retry_queue{retry_where} "
            "ORDER BY user_id, connector_id, external_id, id",
            retry_params,
        ).fetchall()

    factory = connection_factory or get_postgres_connection_factory(settings)
    ensure_postgres_youtube_memory_schema(factory)
    _ensure_migration_ledger(factory)

    memory_inserted = 0
    pipeline_inserted = 0
    retry_inserted = 0
    metrics_inserted = 0
    metric_owner = next(iter(tenant_ids)) if metrics else None

    with factory() as target:
        for row in memories:
            values = tuple(row)
            cur = target.execute(
                """
                INSERT INTO youtube_memories (
                    memory_id, user_id, video_id, url, title, description, channel, channel_id,
                    published_at, duration_sec, thumbnail, playback_position_sec, language,
                    transcript_availability, transcript_kind, transcript_status, tags_json,
                    categories_json, playlist_id, playlist_title, playlist_index, saved_at,
                    user_notes, embedding_status, processing_status, content_hash, chunk_count,
                    duplicate_of, is_duplicate, raw_metadata_json, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                ) ON CONFLICT(user_id, video_id) DO NOTHING
                """,
                (*values[:28], bool(values[28]), *values[29:]),
            )
            memory_inserted += max(int(cur.rowcount or 0), 0)

        for row in pipeline:
            migration_key = _pipeline_migration_key(row)
            claimed = target.execute(
                """
                INSERT INTO youtube_sqlite_migration_ledger (entity_type, migration_key)
                VALUES ('pipeline_stage', %s)
                ON CONFLICT(entity_type, migration_key) DO NOTHING
                """,
                (migration_key,),
            )
            if max(int(claimed.rowcount or 0), 0) == 0:
                continue
            target.execute(
                """
                INSERT INTO youtube_pipeline_runs (
                    run_id, user_id, video_id, capture_id, stage, detail, elapsed_ms, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                tuple(row)[1:],
            )
            pipeline_inserted += 1

        for row in retries:
            values = tuple(row)
            cur = target.execute(
                """
                INSERT INTO youtube_retry_queue (
                    user_id, connector_id, external_id, url, payload_json, attempt_count,
                    max_attempts, next_attempt_at, last_error, dead_lettered, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(user_id, connector_id, external_id) DO NOTHING
                """,
                (*values[1:10], bool(values[10]), *values[11:]),
            )
            retry_inserted += max(int(cur.rowcount or 0), 0)

        if metric_owner is not None:
            for row in metrics:
                cur = target.execute(
                    """
                    INSERT INTO youtube_connector_metrics (
                        user_id, metric_key, connector_id, value_real, value_count, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT(user_id, metric_key, connector_id) DO NOTHING
                    """,
                    (metric_owner, *tuple(row)),
                )
                metrics_inserted += max(int(cur.rowcount or 0), 0)

    return YouTubeStateMigrationReport(
        memories_seen=len(memories),
        memories_inserted=memory_inserted,
        memories_skipped_existing=len(memories) - memory_inserted,
        pipeline_stages_seen=len(pipeline),
        pipeline_stages_inserted=pipeline_inserted,
        pipeline_stages_skipped_existing=len(pipeline) - pipeline_inserted,
        retries_seen=len(retries),
        retries_inserted=retry_inserted,
        retries_skipped_existing=len(retries) - retry_inserted,
        metrics_seen=len(metrics),
        metrics_inserted=metrics_inserted,
        metrics_skipped_existing=len(metrics) - metrics_inserted,
    )


def _ensure_migration_ledger(factory: ConnectionFactory) -> None:
    with factory() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS youtube_sqlite_migration_ledger (
                entity_type TEXT NOT NULL,
                migration_key TEXT NOT NULL,
                PRIMARY KEY(entity_type, migration_key)
            )
            """
        )


def _pipeline_migration_key(row: sqlite3.Row) -> str:
    # Include the legacy surrogate id so two otherwise-identical source events
    # remain distinct, while the same source row remains retry-idempotent.
    encoded = json.dumps(list(row), ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _source_tenants(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        """
        SELECT user_id FROM youtube_memories WHERE user_id IS NOT NULL AND TRIM(user_id) <> ''
        UNION
        SELECT user_id FROM pipeline_runs WHERE user_id IS NOT NULL AND TRIM(user_id) <> ''
        UNION
        SELECT user_id FROM connector_retry_queue
        WHERE connector_id = ? AND user_id IS NOT NULL AND TRIM(user_id) <> ''
        """,
        (CONNECTOR_ID,),
    ).fetchall()
    return {str(row[0]) for row in rows}


def _metrics_attribution_safe(
    tenant_ids: set[str],
    metric_count: int,
    selected_user_id: str | None,
) -> bool:
    if metric_count == 0:
        return True
    if len(tenant_ids) != 1:
        return False
    sole_tenant = next(iter(tenant_ids))
    return selected_user_id is None or selected_user_id == sole_tenant


def _open_source_read_only(settings: Settings) -> sqlite3.Connection:
    source_path = Path(settings.sqlite_path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite migration source does not exist: {source_path}")
    conn = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _normalize_user_id(user_id: str | None) -> str | None:
    if user_id is None:
        return None
    value = user_id.strip()
    if not value:
        raise ValueError("user_id must not be blank")
    return value


def _tenant_filter(user_id: str | None) -> tuple[str, tuple[Any, ...]]:
    if user_id is None:
        return "", ()
    return " WHERE user_id = ?", (user_id,)


def _retry_filter(user_id: str | None) -> tuple[str, tuple[Any, ...]]:
    if user_id is None:
        return " WHERE connector_id = ?", (CONNECTOR_ID,)
    return " WHERE connector_id = ? AND user_id = ?", (CONNECTOR_ID, user_id)


def _count(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> int:
    return int(conn.execute(sql, params).fetchone()[0])
