"""Postgres-backed tenant-scoped import execution/history persistence."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class PostgresImportRunStore:
    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._connection_factory() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS import_runs (
                import_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                connector_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                total_items INTEGER NOT NULL DEFAULT 0,
                completed_items INTEGER NOT NULL DEFAULT 0,
                failed_items INTEGER NOT NULL DEFAULT 0,
                skipped_items INTEGER NOT NULL DEFAULT 0,
                duplicate_items INTEGER NOT NULL DEFAULT 0,
                unsupported_items INTEGER NOT NULL DEFAULT 0,
                detail TEXT NOT NULL DEFAULT '',
                error TEXT,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_import_runs_user ON import_runs(user_id, created_at DESC)")
            conn.execute("""CREATE TABLE IF NOT EXISTS import_run_items (
                id BIGSERIAL PRIMARY KEY,
                import_id TEXT NOT NULL REFERENCES import_runs(import_id) ON DELETE CASCADE,
                user_id TEXT NOT NULL,
                url TEXT NOT NULL,
                external_id TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'queued',
                detail TEXT NOT NULL DEFAULT '',
                error TEXT,
                capture_id TEXT,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_import_items_run ON import_run_items(import_id, status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_import_items_tenant ON import_run_items(user_id, import_id, id)")

    def create(self, *, import_id: str, user_id: str, connector_id: str, items: list[tuple[str, str]], now: str) -> None:
        with self._connection_factory() as conn:
            conn.execute(
                """INSERT INTO import_runs (
                    import_id, user_id, connector_id, status, total_items,
                    completed_items, failed_items, skipped_items, duplicate_items,
                    unsupported_items, detail, created_at, updated_at
                ) VALUES (%s, %s, %s, 'queued', %s, 0, 0, 0, 0, 0, '', %s, %s)""",
                (import_id, user_id, connector_id, len(items), now, now),
            )
            for url, title in items:
                conn.execute(
                    """INSERT INTO import_run_items (
                        import_id, user_id, url, title, status, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, 'queued', %s, %s)""",
                    (import_id, user_id, url, title or "", now, now),
                )

    def list(self, *, user_id: str, limit: int) -> list[dict]:
        with self._connection_factory() as conn:
            rows = conn.execute(
                "SELECT * FROM import_runs WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, *, import_id: str, user_id: str, item_limit: int) -> dict:
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT * FROM import_runs WHERE import_id = %s AND user_id = %s",
                (import_id, user_id),
            ).fetchone()
            if not row:
                raise KeyError("Import not found")
            items = conn.execute(
                """SELECT id, url, title, status, detail, error, external_id
                FROM import_run_items
                WHERE import_id = %s AND user_id = %s
                ORDER BY id ASC LIMIT %s""",
                (import_id, user_id, item_limit),
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) AS c FROM import_run_items WHERE import_id = %s AND user_id = %s",
                (import_id, user_id),
            ).fetchone()
        data = dict(row)
        data["items"] = [dict(item) for item in items]
        data["items_returned"] = len(data["items"])
        data["items_total"] = int(total["c"] if total else 0)
        return data

    def list_pending_items(self, *, import_id: str, user_id: str) -> list[dict]:
        with self._connection_factory() as conn:
            rows = conn.execute(
                "SELECT id, url, title FROM import_run_items WHERE import_id = %s AND user_id = %s ORDER BY id ASC",
                (import_id, user_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def is_cancelled(self, *, import_id: str, user_id: str) -> bool:
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT status FROM import_runs WHERE import_id = %s AND user_id = %s",
                (import_id, user_id),
            ).fetchone()
        return bool(row and row["status"] == "cancelled")

    def cancel_items(self, *, import_id: str, user_id: str, now: str) -> None:
        with self._connection_factory() as conn:
            conn.execute(
                """UPDATE import_run_items
                SET status = 'cancelled', detail = 'Cancelled', updated_at = %s
                WHERE import_id = %s AND user_id = %s AND status IN ('queued', 'processing')""",
                (now, import_id, user_id),
            )

    def update_run(self, *, import_id: str, user_id: str, fields: dict, now: str) -> None:
        allowed = {
            "status", "detail", "error", "completed_items", "failed_items",
            "skipped_items", "duplicate_items", "unsupported_items",
        }
        selected = [(key, value) for key, value in fields.items() if key in allowed]
        sets = [f"{key} = %s" for key, _ in selected] + ["updated_at = %s"]
        values = [value for _, value in selected] + [now, import_id, user_id]
        with self._connection_factory() as conn:
            conn.execute(
                f"UPDATE import_runs SET {', '.join(sets)} WHERE import_id = %s AND user_id = %s",
                values,
            )

    def update_item(self, *, item_id: int, user_id: str, status: str, detail: str, error: str | None, external_id: str, now: str) -> None:
        with self._connection_factory() as conn:
            conn.execute(
                """UPDATE import_run_items
                SET status = %s, detail = %s, error = %s, external_id = %s, updated_at = %s
                WHERE id = %s AND user_id = %s""",
                (status, detail, error, external_id, now, item_id, user_id),
            )
