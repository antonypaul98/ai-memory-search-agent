"""Safe, idempotent SQLite -> Postgres migration for import-run state.

The SQLite source is opened read-only and read inside one snapshot transaction so
run counters and item state come from a consistent source view. Existing
Postgres import IDs are treated as authoritative and are never overwritten; if
a run already exists, all source items for that run are skipped as a unit.

Postgres owns ``import_run_items.id`` (BIGSERIAL), so SQLite surrogate IDs are
used only to preserve deterministic source ordering and are never copied. This
avoids sequence corruption while preserving all business/execution state.
Reports intentionally expose counts only; URLs, titles, errors, connector data,
DSNs, and credentials are never returned.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.db.postgres_import_run_store import PostgresImportRunStore
from app.db.postgres_job_repository import ConnectionFactory
from app.db.postgres_runtime import get_postgres_connection_factory


@dataclass(frozen=True)
class ImportRunMigrationPreview:
    runs: int
    items: int
    tenants: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class ImportRunMigrationReport:
    runs_seen: int
    runs_inserted: int
    runs_skipped_existing: int
    items_seen: int
    items_inserted: int
    items_skipped_existing_run: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def preview_import_run_migration(
    settings: Settings | None = None,
    *,
    user_id: str | None = None,
) -> ImportRunMigrationPreview:
    """Return count-only source information without contacting Postgres."""
    settings = settings or get_settings()
    user_id = _normalize_user_id(user_id)
    with _open_source_read_only(settings) as conn:
        where, params = _tenant_filter(user_id)
        runs = int(conn.execute(f"SELECT COUNT(*) FROM import_runs{where}", params).fetchone()[0])
        items = int(conn.execute(f"SELECT COUNT(*) FROM import_run_items{where}", params).fetchone()[0])
        tenants = int(
            conn.execute(
                f"SELECT COUNT(DISTINCT user_id) FROM import_runs{where}",
                params,
            ).fetchone()[0]
        )
    return ImportRunMigrationPreview(runs=runs, items=items, tenants=tenants)


def migrate_import_runs_to_postgres(
    settings: Settings | None = None,
    *,
    user_id: str | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> ImportRunMigrationReport:
    """Insert missing import runs and their items without overwriting target state."""
    settings = settings or get_settings()
    user_id = _normalize_user_id(user_id)
    factory = connection_factory or get_postgres_connection_factory(settings)
    PostgresImportRunStore(factory)

    with _open_source_read_only(settings) as source:
        # Hold one read snapshot across both tables so counters and item states
        # cannot be observed from different source moments.
        source.execute("BEGIN")
        where, params = _tenant_filter(user_id)
        runs = source.execute(
            "SELECT import_id, user_id, connector_id, status, total_items, "
            "completed_items, failed_items, skipped_items, duplicate_items, "
            "unsupported_items, detail, error, created_at, updated_at "
            f"FROM import_runs{where} ORDER BY user_id, created_at, import_id",
            params,
        ).fetchall()
        items = source.execute(
            "SELECT id, import_id, user_id, url, external_id, title, status, detail, "
            "error, capture_id, created_at, updated_at "
            f"FROM import_run_items{where} ORDER BY user_id, import_id, id",
            params,
        ).fetchall()

    items_by_run: dict[str, list[sqlite3.Row]] = {}
    for item in items:
        items_by_run.setdefault(str(item["import_id"]), []).append(item)

    runs_inserted = 0
    items_inserted = 0
    items_skipped_existing_run = 0
    with factory() as target:
        for run in runs:
            cur = target.execute(
                """
                INSERT INTO import_runs (
                    import_id, user_id, connector_id, status, total_items,
                    completed_items, failed_items, skipped_items, duplicate_items,
                    unsupported_items, detail, error, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(import_id) DO NOTHING
                """,
                tuple(run),
            )
            inserted_run = max(int(cur.rowcount or 0), 0)
            run_items = items_by_run.get(str(run["import_id"]), [])
            if not inserted_run:
                items_skipped_existing_run += len(run_items)
                continue

            runs_inserted += 1
            for item in run_items:
                target.execute(
                    """
                    INSERT INTO import_run_items (
                        import_id, user_id, url, external_id, title, status,
                        detail, error, capture_id, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        item["import_id"],
                        item["user_id"],
                        item["url"],
                        item["external_id"],
                        item["title"],
                        item["status"],
                        item["detail"],
                        item["error"],
                        item["capture_id"],
                        item["created_at"],
                        item["updated_at"],
                    ),
                )
                items_inserted += 1

    return ImportRunMigrationReport(
        runs_seen=len(runs),
        runs_inserted=runs_inserted,
        runs_skipped_existing=len(runs) - runs_inserted,
        items_seen=len(items),
        items_inserted=items_inserted,
        items_skipped_existing_run=items_skipped_existing_run,
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
