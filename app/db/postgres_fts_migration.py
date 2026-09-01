"""Safe, tenant-explicit SQLite -> Postgres lexical backfill for P-03.

The historical SQLite FTS5 table has no tenant column. Therefore this helper
never attempts to infer ownership: callers must provide the exact tenant that
owns the local source database. The source is opened read-only and existing
Postgres rows are preserved, making the transfer safe to retry without
clobbering newer target-side lexical documents.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.db.postgres_job_repository import ConnectionFactory
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.postgres_fts_index import PostgresFTSIndex


@dataclass(frozen=True)
class LexicalMigrationPreview:
    documents: int
    tenant: str

    def to_dict(self) -> dict[str, int | str]:
        return asdict(self)


@dataclass(frozen=True)
class LexicalMigrationReport:
    documents_seen: int
    documents_inserted: int
    documents_skipped_existing: int
    tenant: str

    def to_dict(self) -> dict[str, int | str]:
        return asdict(self)


def preview_lexical_migration(
    settings: Settings | None = None,
    *,
    user_id: str,
) -> LexicalMigrationPreview:
    """Return count-only source information without contacting Postgres."""
    tenant = _require_tenant(user_id)
    settings = settings or get_settings()
    with _open_source_read_only(settings) as conn:
        documents = int(conn.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0])
    return LexicalMigrationPreview(documents=documents, tenant=tenant)


def migrate_lexical_to_postgres(
    settings: Settings | None = None,
    *,
    user_id: str,
    connection_factory: ConnectionFactory | None = None,
) -> LexicalMigrationReport:
    """Insert missing legacy lexical documents for exactly one explicit tenant.

    Existing target rows are deliberately left untouched. This makes retries
    idempotent and prevents a stale SQLite snapshot from replacing newer
    Postgres documents produced after cutover.
    """
    tenant = _require_tenant(user_id)
    settings = settings or get_settings()
    factory = connection_factory or get_postgres_connection_factory(settings)
    # Reuse the production primitive to create/validate the exact target schema.
    PostgresFTSIndex(factory)

    with _open_source_read_only(settings) as source:
        rows = source.execute(
            "SELECT video_id, level, doc_id, title, body "
            "FROM memory_fts ORDER BY doc_id, video_id, level"
        ).fetchall()

    inserted = 0
    with factory() as target:
        for row in rows:
            cur = target.execute(
                """
                INSERT INTO memory_fts_documents (
                    user_id, video_id, level, doc_id, title, body
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(user_id, doc_id) DO NOTHING
                """,
                (tenant, row["video_id"], row["level"], row["doc_id"], row["title"], row["body"]),
            )
            inserted += max(int(cur.rowcount or 0), 0)

    return LexicalMigrationReport(
        documents_seen=len(rows),
        documents_inserted=inserted,
        documents_skipped_existing=len(rows) - inserted,
        tenant=tenant,
    )


def _require_tenant(user_id: str) -> str:
    tenant = user_id.strip()
    if not tenant:
        raise ValueError(
            "user_id is required because the legacy SQLite FTS table has no tenant identity"
        )
    return tenant


def _open_source_read_only(settings: Settings) -> sqlite3.Connection:
    source_path = Path(settings.sqlite_path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite migration source does not exist: {source_path}")
    conn = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn
