"""Safe, idempotent SQLite to Postgres migration for intelligence events."""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.db.postgres_intelligence_event_store import PostgresIntelligenceEventStore
from app.db.postgres_job_repository import ConnectionFactory
from app.db.postgres_runtime import get_postgres_connection_factory


@dataclass(frozen=True)
class IntelligenceEventMigrationPreview:
    events: int
    tenants: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class IntelligenceEventMigrationReport:
    events_seen: int
    events_inserted: int
    events_skipped_existing: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def preview_intelligence_event_migration(
    settings: Settings | None = None, *, user_id: str | None = None
) -> IntelligenceEventMigrationPreview:
    settings = settings or get_settings()
    user_id = _normalize_user_id(user_id)
    where, params = _tenant_filter(user_id)
    with _open_source_read_only(settings) as conn:
        events = int(conn.execute(f"SELECT COUNT(*) FROM intelligence_events{where}", params).fetchone()[0])
        tenants = int(
            conn.execute(
                f"SELECT COUNT(DISTINCT user_id) FROM intelligence_events{where}", params
            ).fetchone()[0]
        )
    return IntelligenceEventMigrationPreview(events=events, tenants=tenants)


def migrate_intelligence_events_to_postgres(
    settings: Settings | None = None,
    *,
    user_id: str | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> IntelligenceEventMigrationReport:
    settings = settings or get_settings()
    user_id = _normalize_user_id(user_id)
    factory = connection_factory or get_postgres_connection_factory(settings)
    PostgresIntelligenceEventStore(factory)
    where, params = _tenant_filter(user_id)
    with _open_source_read_only(settings) as source:
        rows = source.execute(
            "SELECT id,user_id,event_type,topic,video_id,query,created_at "
            f"FROM intelligence_events{where} "
            "ORDER BY user_id, created_at, id",
            params,
        ).fetchall()

    normalized_rows = _validate_source_rows(rows)
    inserted = 0
    with factory() as target:
        for row in normalized_rows:
            cur = target.execute(
                """INSERT INTO intelligence_events (
                    id,user_id,event_type,topic,video_id,query,created_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(id) DO NOTHING""",
                row,
            )
            inserted += max(int(cur.rowcount or 0), 0)
        target.execute(
            """SELECT setval(
                pg_get_serial_sequence('intelligence_events', 'id'),
                GREATEST(COALESCE((SELECT MAX(id) FROM intelligence_events), 1), 1),
                EXISTS(SELECT 1 FROM intelligence_events)
            )"""
        )

    return IntelligenceEventMigrationReport(
        events_seen=len(normalized_rows),
        events_inserted=inserted,
        events_skipped_existing=len(normalized_rows) - inserted,
    )


def _validate_source_rows(rows: list[sqlite3.Row]) -> list[tuple[Any, ...]]:
    seen_ids: set[int] = set()
    normalized: list[tuple[Any, ...]] = []
    for row in rows:
        event_id = int(row["id"])
        user_id = str(row["user_id"] or "").strip()
        event_type = str(row["event_type"] or "").strip()
        if event_id <= 0 or not user_id or not event_type:
            raise ValueError("intelligence event contains an invalid identity")
        if event_id in seen_ids:
            raise ValueError("intelligence event source contains duplicate id")
        seen_ids.add(event_id)

        raw_created_at = str(row["created_at"] or "").strip()
        if not raw_created_at:
            raise ValueError("intelligence event contains a blank created_at")
        try:
            parsed = datetime.fromisoformat(raw_created_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("intelligence event contains invalid created_at") from exc
        if parsed.tzinfo is None:
            raise ValueError("intelligence event created_at must include timezone")
        created_at = parsed.astimezone(timezone.utc)
        normalized.append(
            (
                event_id,
                user_id,
                event_type,
                row["topic"],
                row["video_id"],
                row["query"],
                created_at,
            )
        )
    return normalized


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
    return ("", ()) if user_id is None else (" WHERE user_id = ?", (user_id,))
