"""Postgres persistence for tenant-scoped capture state."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


ConnectionFactory = Callable[[], Any]


class PostgresCaptureStore:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self._connection_factory() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS captures (
                    capture_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    url_hash TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    source_type TEXT NOT NULL DEFAULT 'web',
                    status TEXT NOT NULL,
                    job_id TEXT,
                    stage TEXT NOT NULL DEFAULT '',
                    stage_detail TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '',
                    error TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_captures_tenant_updated ON captures(user_id, updated_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_captures_tenant_hash ON captures(user_id, url_hash)"
            )

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
        with self._connection_factory() as conn:
            conn.execute(
                """
                INSERT INTO captures (
                    capture_id, user_id, url, url_hash, title, source_type, status,
                    stage, stage_detail, payload_json, error, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    capture_id, user_id, url, url_hash, title, source_type,
                    "queued", "queued", "Added to Memory", payload_json, None, now, now,
                ),
            )

    def get_retry_payload(self, capture_id: str, *, user_id: str) -> dict | None:
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT payload_json, status FROM captures WHERE capture_id = %s AND user_id = %s",
                (capture_id, user_id),
            ).fetchone()
        return dict(row) if row else None

    def get_status(self, capture_id: str, *, user_id: str) -> dict | None:
        with self._connection_factory() as conn:
            row = conn.execute(
                """
                SELECT capture_id, status, stage, stage_detail, url, title, job_id, error
                FROM captures WHERE capture_id = %s AND user_id = %s
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
        with self._connection_factory() as conn:
            if title is not None:
                conn.execute(
                    """
                    UPDATE captures
                    SET status = %s, stage = %s, stage_detail = %s, error = %s,
                        title = %s, updated_at = %s
                    WHERE capture_id = %s AND user_id = %s
                    """,
                    (status, stage, detail, error, title, now, capture_id, user_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE captures
                    SET status = %s, stage = %s, stage_detail = %s, error = %s, updated_at = %s
                    WHERE capture_id = %s AND user_id = %s
                    """,
                    (status, stage, detail, error, now, capture_id, user_id),
                )

    def rewrite_payload(self, capture_id: str, *, user_id: str, payload_json: str, now: str) -> None:
        with self._connection_factory() as conn:
            conn.execute(
                "UPDATE captures SET payload_json = %s, updated_at = %s WHERE capture_id = %s AND user_id = %s",
                (payload_json, now, capture_id, user_id),
            )
