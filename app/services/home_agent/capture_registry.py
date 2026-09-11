"""Server-side registry for bounded Home Agent capture sessions.

Clients receive opaque session IDs only. Session ownership, source binding, and
expiry remain server-controlled and are revalidated on lookup.
"""

from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock

from .capture_session import CaptureSession


class CaptureSessionRegistry:
    """Thread-safe in-process registry for short-lived capture sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, CaptureSession] = {}
        self._lock = RLock()

    def register(self, session: CaptureSession) -> None:
        """Store a server-issued session by its opaque ID."""
        with self._lock:
            self._sessions[session.session_id] = session

    def resolve_for_user(
        self,
        *,
        session_id: str,
        user_id: str,
        now: datetime | None = None,
    ) -> CaptureSession:
        """Resolve an active session for its authenticated owner.

        The stored session remains the authority for source_id and expiry so API
        callers cannot choose either value during detection ingest.
        """
        if not session_id.strip():
            raise ValueError("session_id is required")
        if not user_id.strip():
            raise ValueError("user_id is required")

        resolved_now = now or datetime.now(timezone.utc)
        if resolved_now.tzinfo is None or resolved_now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")

        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise PermissionError("capture session is missing, mismatched, or expired")

            if resolved_now < session.started_at or resolved_now >= session.expires_at:
                self._sessions.pop(session_id, None)
                raise PermissionError("capture session is missing, mismatched, or expired")

            if session.user_id != user_id:
                raise PermissionError("capture session is missing, mismatched, or expired")

            return session

    def resolve(
        self,
        *,
        session_id: str,
        user_id: str,
        source_id: str,
        now: datetime | None = None,
    ) -> CaptureSession:
        """Resolve only an active session owned by this user and source."""
        if not source_id.strip():
            raise ValueError("source_id is required")

        session = self.resolve_for_user(
            session_id=session_id,
            user_id=user_id,
            now=now,
        )
        if session.source_id != source_id:
            raise PermissionError("capture session is missing, mismatched, or expired")
        return session

    def revoke(self, *, session_id: str) -> bool:
        """Remove a session; return whether one existed."""
        if not session_id.strip():
            raise ValueError("session_id is required")
        with self._lock:
            return self._sessions.pop(session_id, None) is not None
