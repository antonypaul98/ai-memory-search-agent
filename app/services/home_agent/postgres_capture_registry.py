"""Shared PostgreSQL capture-session registry for cross-worker resolution.

This is a point-in-time authorization primitive, not an atomic image-write
permission check. The evidence writer still needs a transaction-scoped session
lock to prevent a revocation race. Not wired into production in this slice.
"""
from __future__ import annotations

from datetime import datetime

from app.db.account_erasure_fence import require_active_tenant
from .capture_registry import CaptureSessionRegistry
from .capture_session import CaptureSession


class PostgresCaptureSessionRegistry(CaptureSessionRegistry):
    """Keep server-issued sessions in the shared database, not worker memory."""

    def __init__(self, connection_factory):
        self._connect = connection_factory
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS home_capture_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    started_at TIMESTAMPTZ NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    revoked_at TIMESTAMPTZ,
                    CHECK (expires_at > started_at),
                    CHECK (expires_at <= started_at + INTERVAL '15 minutes')
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_home_capture_sessions_tenant
                ON home_capture_sessions(user_id, source_id)
            """)

    def register(self, session: CaptureSession) -> None:
        if not isinstance(session, CaptureSession):
            raise TypeError("server-issued capture session required")
        with self._connect() as conn:
            require_active_tenant(conn, user_id=session.user_id)
            row = conn.execute("""
                INSERT INTO home_capture_sessions
                    (session_id, user_id, source_id, started_at, expires_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (session_id) DO NOTHING
                RETURNING session_id
            """, (session.session_id, session.user_id, session.source_id,
                  session.started_at, session.expires_at)).fetchone()
            if row is None:
                raise ValueError("capture session ID already registered")

    def resolve(
        self, *, session_id: str, user_id: str, source_id: str,
        now: datetime | None = None,
    ) -> CaptureSession:
        # Keep the in-memory registry's signature, but never trust an
        # application-supplied time for database authorization.
        if not all(isinstance(v, str) and v.strip() and v == v.strip()
                   for v in (session_id, user_id, source_id)):
            raise ValueError("capture session, tenant and source are required")
        with self._connect() as conn:
            row = conn.execute("""
                SELECT session_id, user_id, source_id, started_at, expires_at
                FROM home_capture_sessions
                WHERE session_id=%s AND user_id=%s AND source_id=%s
                  AND revoked_at IS NULL
                  AND started_at <= clock_timestamp()
                  AND expires_at > clock_timestamp()
            """, (session_id, user_id, source_id)).fetchone()
        if row is None:
            raise PermissionError("capture session is missing, mismatched, revoked, or expired")
        return CaptureSession(**dict(row))

    def revoke(self, *, session_id: str) -> bool:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id is required")
        with self._connect() as conn:
            row = conn.execute("""
                UPDATE home_capture_sessions SET revoked_at=clock_timestamp()
                WHERE session_id=%s AND revoked_at IS NULL
                RETURNING session_id
            """, (session_id,)).fetchone()
        return row is not None

    def revoke_for_user(self, *, user_id: str) -> int:
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("user_id is required")
        with self._connect() as conn:
            rows = conn.execute("""
                UPDATE home_capture_sessions SET revoked_at=clock_timestamp()
                WHERE user_id=%s AND revoked_at IS NULL
                RETURNING session_id
            """, (user_id,)).fetchall()
        return len(rows)
