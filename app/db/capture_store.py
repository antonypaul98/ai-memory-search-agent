"""Tenant-scoped capture state persistence.

SQLite remains the local/self-host default.  Production backend selection lives
in ``capture_store_factory`` so capture orchestration does not depend on SQL.
"""

from __future__ import annotations

from app.config import Settings
from app.db.schema import get_connection, migrate


class CaptureStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        migrate(settings)

    def create(
        self,
        *,
        capture_id: str,
        user_id: str,
        url: str,
        url_hash: str,
        title: str,
        source_type: str,
        payload_json: str,
        now: str,
    ) -> None:
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT INTO captures (
                    capture_id, user_id, url, url_hash, title, source_type, status,
                    stage, stage_detail, payload_json, error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    capture_id, user_id, url, url_hash, title, source_type,
                    "queued", "queued", "Added to Memory", payload_json, None, now, now,
                ),
            )

    def get_retry_payload(self, capture_id: str, *, user_id: str) -> dict | None:
        with get_connection(self._settings) as conn:
            row = conn.execute(
                "SELECT payload_json, status FROM captures WHERE capture_id = ? AND user_id = ?",
                (capture_id, user_id),
            ).fetchone()
        return dict(row) if row else None

    def get_status(self, capture_id: str, *, user_id: str) -> dict | None:
        with get_connection(self._settings) as conn:
            row = conn.execute(
                """
                SELECT capture_id, status, stage, stage_detail, url, title, job_id, error
                FROM captures WHERE capture_id = ? AND user_id = ?
                """,
                (capture_id, user_id),
            ).fetchone()
        return dict(row) if row else None

    def update_stage(
        self,
        capture_id: str,
        *,
        user_id: str,
        status: str,
        stage: str,
        detail: str,
        error: str | None,
        title: str | None,
        now: str,
    ) -> None:
        with get_connection(self._settings) as conn:
            if title is not None:
                conn.execute(
                    """
                    UPDATE captures
                    SET status = ?, stage = ?, stage_detail = ?, error = ?, title = ?, updated_at = ?
                    WHERE capture_id = ? AND user_id = ?
                    """,
                    (status, stage, detail, error, title, now, capture_id, user_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE captures
                    SET status = ?, stage = ?, stage_detail = ?, error = ?, updated_at = ?
                    WHERE capture_id = ? AND user_id = ?
                    """,
                    (status, stage, detail, error, now, capture_id, user_id),
                )

    def rewrite_payload(self, capture_id: str, *, user_id: str, payload_json: str, now: str) -> None:
        with get_connection(self._settings) as conn:
            conn.execute(
                "UPDATE captures SET payload_json = ?, updated_at = ? WHERE capture_id = ? AND user_id = ?",
                (payload_json, now, capture_id, user_id),
            )
