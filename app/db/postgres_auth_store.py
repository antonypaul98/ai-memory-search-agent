"""Postgres-backed user and session persistence for GAP-02.

This store mirrors the existing SQLite AuthStore contract while keeping database
credentials environment-owned through the shared Postgres runtime. It does not
fall back to SQLite when Postgres is explicitly selected.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import Settings
from app.core.security import hash_password, new_session_token, verify_password
from app.db.auth_store import _auth_secret
from app.db.postgres_job_repository import ConnectionFactory
from app.models.user import LOCAL_DEFAULT_USER_ID, UserPublic


class PostgresAuthStore:
    def __init__(self, settings: Settings, connection_factory: ConnectionFactory) -> None:
        self._settings = settings
        self._connection_factory = connection_factory

    def ensure_local_user(self) -> None:
        with self._connection_factory() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, email, password_hash, display_name, created_at)
                VALUES (%s, NULL, NULL, 'Local Demo User', %s)
                ON CONFLICT (user_id) DO NOTHING
                """,
                (LOCAL_DEFAULT_USER_ID, _utc_now()),
            )

    def create_user(self, *, email: str, password: str, display_name: str) -> UserPublic:
        secret = _auth_secret(self._settings)
        normalized_email = email.lower().strip()
        user_id = normalized_email.replace("@", "_at_")
        resolved_name = display_name or normalized_email
        with self._connection_factory() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, email, password_hash, display_name, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    normalized_email,
                    hash_password(password, secret=secret),
                    resolved_name,
                    _utc_now(),
                ),
            )
        return UserPublic(user_id=user_id, email=normalized_email, display_name=resolved_name)

    def authenticate(self, *, email: str, password: str) -> UserPublic | None:
        secret = _auth_secret(self._settings)
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT user_id, email, password_hash, display_name FROM users WHERE email = %s",
                (email.lower().strip(),),
            ).fetchone()
        if not row or not _value(row, "password_hash"):
            return None
        if not verify_password(password, str(_value(row, "password_hash")), secret=secret):
            return None
        return UserPublic(
            user_id=str(_value(row, "user_id")),
            email=_value(row, "email"),
            display_name=str(_value(row, "display_name")),
        )

    def create_session(self, user_id: str) -> str:
        token = new_session_token()
        expires = datetime.now(timezone.utc) + timedelta(hours=self._settings.session_ttl_hours)
        with self._connection_factory() as conn:
            conn.execute(
                """
                INSERT INTO sessions (token, user_id, expires_at, created_at)
                VALUES (%s, %s, %s, %s)
                """,
                (token, user_id, expires, _utc_now()),
            )
        return token

    def resolve_token(self, token: str) -> UserPublic | None:
        if not token or not token.strip():
            return None
        now = datetime.now(timezone.utc)
        with self._connection_factory() as conn:
            conn.execute(
                "DELETE FROM sessions WHERE token = %s AND expires_at <= %s",
                (token, now),
            )
            row = conn.execute(
                """
                SELECT s.user_id, u.email, u.display_name
                FROM sessions s
                JOIN users u ON u.user_id = s.user_id
                WHERE s.token = %s AND s.expires_at > %s
                """,
                (token, now),
            ).fetchone()
        if not row:
            return None
        return UserPublic(
            user_id=str(_value(row, "user_id")),
            email=_value(row, "email"),
            display_name=str(_value(row, "display_name")),
        )

    def revoke_session(self, token: str) -> bool:
        with self._connection_factory() as conn:
            cur = conn.execute("DELETE FROM sessions WHERE token = %s", (token,))
            return int(cur.rowcount) > 0

    def revoke_all_sessions(self, user_id: str) -> int:
        with self._connection_factory() as conn:
            cur = conn.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
            return int(cur.rowcount)


def ensure_postgres_auth_schema(connection_factory: ConnectionFactory) -> None:
    """Create only the auth/session relational surface, idempotently."""
    with connection_factory() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                email TEXT UNIQUE,
                password_hash TEXT,
                display_name TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at)"
        )


def _value(row: Any, key: str) -> Any:
    """Support psycopg dict rows and simple test doubles."""
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        index = {
            "user_id": 0,
            "email": 1,
            "password_hash": 2,
            "display_name": 3,
        }[key]
        return row[index]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
