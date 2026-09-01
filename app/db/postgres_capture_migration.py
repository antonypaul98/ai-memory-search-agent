"""Safe, idempotent SQLite -> Postgres migration for capture state.

The SQLite source is opened read-only. Existing Postgres capture IDs are never
overwritten, so retrying a migration cannot clobber newer target-side state.
Reports intentionally expose counts only; capture URLs, titles, payloads, errors,
DSNs, and credentials are never returned.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.db.postgres_capture_store import PostgresCaptureStore
from app.db.postgres_job_repository import ConnectionFactory
from app.db.postgres_runtime import get_postgres_connection_factory


@dataclass(frozen=True)
class CaptureMigrationPreview:
    captures: int
    tenants: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class CaptureMigrationReport:
    captures_seen: int
    captures_inserted: int
    captures_skipped_existing: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def preview_capture_migration(
    settings: Settings | None = None,
    *,
    user_id: str | None = None,
) -> CaptureMigrationPreview:
    """Return count-only source information without contacting Postgres."""
    settings = settings or get_settings()
    user_id = _normalize_user_id(user_id)
    with _open_source_read_only(settings) as conn:
        where, params = _tenant_filter(user_id)
        captures = int(conn.execute(f"SELECT COUNT(*) FROM captures{where}", params).fetchone()[0])
        tenants = int(
            conn.execute(
                f"SELECT COUNT(DISTINCT user_id) FROM captures{where}",
                params,
            ).fetchone()[0]
        )
    return CaptureMigrationPreview(captures=captures, tenants=tenants)


def migrate_captures_to_postgres(
    settings: Settings | None = None,
    *,
    user_id: str | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> CaptureMigrationReport:
    """Insert missing SQLite capture rows into Postgres without overwriting."""
    settings = settings or get_settings()
    user_id = _normalize_user_id(user_id)
    factory = connection_factory or get_postgres_connection_factory(settings)
    PostgresCaptureStore(factory)

    with _open_source_read_only(settings) as source:
        where, params = _tenant_filter(user_id)
        rows = source.execute(
            "SELECT capture_id, user_id, url, url_hash, title, source_type, status, "
            "job_id, stage, stage_detail, payload_json, error, created_at, updated_at "
            f"FROM captures{where} ORDER BY user_id, capture_id",
            params,
        ).fetchall()

    inserted = 0
    with factory() as target:
        for row in rows:
            cur = target.execute(
                """
                INSERT INTO captures (
                    capture_id, user_id, url, url_hash, title, source_type, status,
                    job_id, stage, stage_detail, payload_json, error, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(capture_id) DO NOTHING
                """,
                tuple(row),
            )
            inserted += max(int(cur.rowcount or 0), 0)

    return CaptureMigrationReport(
        captures_seen=len(rows),
        captures_inserted=inserted,
        captures_skipped_existing=len(rows) - inserted,
    )


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
