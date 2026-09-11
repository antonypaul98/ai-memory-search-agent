"""Safe tenant-scoped SQLite -> Postgres migration for cross-source dedup state."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

from app.config import Settings, get_settings
from app.db.postgres_content_url_index_store import ensure_postgres_content_url_index_schema
from app.db.postgres_job_repository import ConnectionFactory
from app.db.postgres_runtime import get_postgres_connection_factory


@dataclass(frozen=True)
class ContentUrlIndexMigrationPreview:
    rows: int
    tenant: str

    def to_dict(self) -> dict[str, int | str]:
        return asdict(self)


@dataclass(frozen=True)
class ContentUrlIndexMigrationReport:
    rows_seen: int
    rows_written: int
    rows_skipped_existing: int
    tenant: str

    def to_dict(self) -> dict[str, int | str]:
        return asdict(self)


def preview_content_url_index_migration(
    settings: Settings | None = None,
    *,
    user_id: str,
) -> ContentUrlIndexMigrationPreview:
    tenant = _require_tenant(user_id)
    settings = settings or get_settings()
    with _open_source_read_only(settings) as source:
        rows = _read_source_rows(source, tenant=tenant)
    return ContentUrlIndexMigrationPreview(rows=len(rows), tenant=tenant)


def migrate_content_url_index_to_postgres(
    settings: Settings | None = None,
    *,
    user_id: str,
    connection_factory: ConnectionFactory | None = None,
) -> ContentUrlIndexMigrationReport:
    """Copy one exact tenant while preserving target rows written after cutover."""
    tenant = _require_tenant(user_id)
    settings = settings or get_settings()
    with _open_source_read_only(settings) as source:
        rows = _read_source_rows(source, tenant=tenant)

    factory = connection_factory or get_postgres_connection_factory(settings)
    ensure_postgres_content_url_index_schema(factory)

    written = 0
    with factory() as target:
        for row in rows:
            cur = target.execute(
                """
                INSERT INTO content_url_index (
                    user_id, url_hash, canonical_url, content_hash,
                    source_type, connector_id, external_id, memory_id, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(user_id, url_hash) DO NOTHING
                """,
                (
                    tenant,
                    row["url_hash"],
                    row["canonical_url"],
                    row["content_hash"],
                    row["source_type"],
                    row["connector_id"],
                    row["external_id"],
                    row["memory_id"],
                    row["created_at"],
                ),
            )
            written += max(int(cur.rowcount or 0), 0)

        target_rows = target.execute(
            "SELECT url_hash FROM content_url_index WHERE user_id = %s ORDER BY url_hash",
            (tenant,),
        ).fetchall()
        target_hashes = {_row_value(row, "url_hash") for row in target_rows}
        source_hashes = {str(row["url_hash"]) for row in rows}
        missing_count = len(source_hashes - target_hashes)
        if missing_count:
            raise RuntimeError(
                f"content URL index migration parity failed: target missing {missing_count} source identities"
            )

    return ContentUrlIndexMigrationReport(
        rows_seen=len(rows),
        rows_written=written,
        rows_skipped_existing=len(rows) - written,
        tenant=tenant,
    )


def _read_source_rows(source: sqlite3.Connection, *, tenant: str) -> list[sqlite3.Row]:
    if not source.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='content_url_index'"
    ).fetchone():
        raise ValueError("content_url_index migration source table is missing")
    return source.execute(
        """
        SELECT user_id, url_hash, canonical_url, content_hash, source_type,
               connector_id, external_id, memory_id, created_at
        FROM content_url_index
        WHERE user_id = ?
        ORDER BY created_at ASC, url_hash ASC
        """,
        (tenant,),
    ).fetchall()


def _require_tenant(user_id: str) -> str:
    if not isinstance(user_id, str) or not user_id or user_id != user_id.strip():
        raise ValueError("user_id must be a non-blank exact tenant identity")
    return user_id


def _row_value(row, key: str) -> str:
    if isinstance(row, dict):
        return str(row[key])
    try:
        return str(row[key])
    except (TypeError, KeyError, IndexError):
        return str(row[0])


@contextmanager
def _open_source_read_only(settings: Settings) -> Iterator[sqlite3.Connection]:
    source_path = Path(settings.sqlite_path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite migration source does not exist: {source_path}")
    conn = sqlite3.connect(f"{source_path.as_uri()}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        conn.execute("BEGIN")
        yield conn
    finally:
        conn.close()
