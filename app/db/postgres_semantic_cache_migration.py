"""Safe SQLite -> Postgres semantic-cache transfer for P-03.

Semantic cache rows are disposable derived state. This helper exists only for
operators who deliberately want to retain compatible cache entries during a
Postgres cutover. It opens SQLite read-only, preserves tenant identity, copies
only rows compatible with the target cache versions, and never overwrites a
Postgres cache row.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.db.postgres_job_repository import ConnectionFactory
from app.db.postgres_runtime import get_postgres_connection_factory
from app.db.postgres_semantic_cache_store import PostgresSemanticCacheStore


@dataclass(frozen=True)
class SemanticCacheMigrationPreview:
    rows: int
    tenants: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class SemanticCacheMigrationReport:
    rows_seen: int
    rows_compatible: int
    rows_inserted: int
    rows_skipped_incompatible: int
    rows_skipped_existing: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def preview_semantic_cache_migration(
    settings: Settings | None = None,
    *,
    user_id: str | None = None,
) -> SemanticCacheMigrationPreview:
    """Return count-only source information without contacting Postgres."""
    settings = settings or get_settings()
    with _open_source_read_only(settings) as conn:
        if user_id is None:
            row = conn.execute(
                "SELECT COUNT(*) AS rows, COUNT(DISTINCT user_id) AS tenants FROM semantic_cache"
            ).fetchone()
        else:
            tenant = _require_tenant(user_id)
            row = conn.execute(
                "SELECT COUNT(*) AS rows, COUNT(DISTINCT user_id) AS tenants "
                "FROM semantic_cache WHERE user_id = ?",
                (tenant,),
            ).fetchone()
    return SemanticCacheMigrationPreview(rows=int(row["rows"] or 0), tenants=int(row["tenants"] or 0))


def migrate_semantic_cache_to_postgres(
    settings: Settings | None = None,
    *,
    user_id: str | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> SemanticCacheMigrationReport:
    """Insert compatible, missing cache rows while preserving target state."""
    settings = settings or get_settings()
    tenant = _require_tenant(user_id) if user_id is not None else None
    factory = connection_factory or get_postgres_connection_factory(settings)
    target_store = PostgresSemanticCacheStore(factory)
    target_index_version, target_preference_version = target_store.versions()

    with _open_source_read_only(settings) as source:
        sql = (
            "SELECT user_id, cache_key, question_normalized, question_embedding, answer_json, "
            "query_type, memory_index_version, preference_version, created_at, expires_at "
            "FROM semantic_cache"
        )
        params: tuple[Any, ...] = ()
        if tenant is not None:
            sql += " WHERE user_id = ?"
            params = (tenant,)
        sql += " ORDER BY user_id, cache_key"
        rows = source.execute(sql, params).fetchall()

    compatible = [
        row
        for row in rows
        if str(row["memory_index_version"]) == target_index_version
        and str(row["preference_version"]) == target_preference_version
    ]

    inserted = 0
    with factory() as target:
        for row in compatible:
            cur = target.execute(
                """
                INSERT INTO semantic_cache (
                    user_id, cache_key, question_normalized, question_embedding, answer_json,
                    query_type, memory_index_version, preference_version, created_at, expires_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(user_id, cache_key) DO NOTHING
                """,
                (
                    row["user_id"],
                    row["cache_key"],
                    row["question_normalized"],
                    _embedding_bytes(row["question_embedding"]),
                    row["answer_json"],
                    row["query_type"],
                    row["memory_index_version"],
                    row["preference_version"],
                    row["created_at"],
                    row["expires_at"],
                ),
            )
            inserted += max(int(cur.rowcount or 0), 0)

    return SemanticCacheMigrationReport(
        rows_seen=len(rows),
        rows_compatible=len(compatible),
        rows_inserted=inserted,
        rows_skipped_incompatible=len(rows) - len(compatible),
        rows_skipped_existing=len(compatible) - inserted,
    )


def _embedding_bytes(value: Any) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, bytes):
        return value
    return str(value).encode("utf-8")


def _require_tenant(user_id: str) -> str:
    tenant = user_id.strip()
    if not tenant:
        raise ValueError("user_id must be non-empty when semantic-cache migration is tenant-scoped")
    return tenant


def _open_source_read_only(settings: Settings) -> sqlite3.Connection:
    source_path = Path(settings.sqlite_path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite migration source does not exist: {source_path}")
    conn = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn
