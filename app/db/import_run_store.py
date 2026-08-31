"""Tenant-scoped import-run persistence.

This preserves the historical SQLite behavior behind a store boundary so the
production profile can switch import execution/history to Postgres explicitly.
"""

from __future__ import annotations

from app.config import Settings
from app.db.schema import get_connection, migrate


class ImportRunStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        migrate(settings)

    def create(self, *, import_id: str, user_id: str, connector_id: str, items: list[tuple[str, str]], now: str) -> None:
        with get_connection(self._settings) as conn:
            conn.execute(
                """INSERT INTO import_runs (
                    import_id, user_id, connector_id, status, total_items,
                    completed_items, failed_items, skipped_items, duplicate_items,
                    unsupported_items, detail, created_at, updated_at
                ) VALUES (?, ?, ?, 'queued', ?, 0, 0, 0, 0, 0, '', ?, ?)""",
                (import_id, user_id, connector_id, len(items), now, now),
            )
            for url, title in items:
                conn.execute(
                    """INSERT INTO import_run_items (
                        import_id, user_id, url, title, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'queued', ?, ?)""",
                    (import_id, user_id, url, title or "", now, now),
                )

    def list(self, *, user_id: str, limit: int) -> list[dict]:
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                "SELECT * FROM import_runs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, *, import_id: str, user_id: str, item_limit: int) -> dict:
        with get_connection(self._settings) as conn:
            row = conn.execute(
                "SELECT * FROM import_runs WHERE import_id = ? AND user_id = ?",
                (import_id, user_id),
            ).fetchone()
            if not row:
                raise KeyError("Import not found")
            items = conn.execute(
                """SELECT id, url, title, status, detail, error, external_id
                FROM import_run_items
                WHERE import_id = ? AND user_id = ?
                ORDER BY id ASC LIMIT ?""",
                (import_id, user_id, item_limit),
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) AS c FROM import_run_items WHERE import_id = ? AND user_id = ?",
                (import_id, user_id),
            ).fetchone()
        data = dict(row)
        data["items"] = [dict(item) for item in items]
        data["items_returned"] = len(data["items"])
        data["items_total"] = int(total["c"] if total else 0)
        return data

    def list_pending_items(self, *, import_id: str, user_id: str) -> list[dict]:
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                "SELECT id, url, title FROM import_run_items WHERE import_id = ? AND user_id = ? ORDER BY id ASC",
                (import_id, user_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def is_cancelled(self, *, import_id: str, user_id: str) -> bool:
        with get_connection(self._settings) as conn:
            row = conn.execute(
                "SELECT status FROM import_runs WHERE import_id = ? AND user_id = ?",
                (import_id, user_id),
            ).fetchone()
        return bool(row and row["status"] == "cancelled")

    def cancel_items(self, *, import_id: str, user_id: str, now: str) -> None:
        with get_connection(self._settings) as conn:
            conn.execute(
                """UPDATE import_run_items
                SET status = 'cancelled', detail = 'Cancelled', updated_at = ?
                WHERE import_id = ? AND user_id = ? AND status IN ('queued', 'processing')""",
                (now, import_id, user_id),
            )

    def update_run(self, *, import_id: str, user_id: str, fields: dict, now: str) -> None:
        allowed = {
            "status", "detail", "error", "completed_items", "failed_items",
            "skipped_items", "duplicate_items", "unsupported_items",
        }
        selected = [(key, value) for key, value in fields.items() if key in allowed]
        sets = [f"{key} = ?" for key, _ in selected] + ["updated_at = ?"]
        values = [value for _, value in selected] + [now, import_id, user_id]
        with get_connection(self._settings) as conn:
            conn.execute(
                f"UPDATE import_runs SET {', '.join(sets)} WHERE import_id = ? AND user_id = ?",
                values,
            )

    def update_item(self, *, item_id: int, user_id: str, status: str, detail: str, error: str | None, external_id: str, now: str) -> None:
        with get_connection(self._settings) as conn:
            conn.execute(
                """UPDATE import_run_items
                SET status = ?, detail = ?, error = ?, external_id = ?, updated_at = ?
                WHERE id = ? AND user_id = ?""",
                (status, detail, error, external_id, now, item_id, user_id),
            )
