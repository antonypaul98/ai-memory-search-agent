"""User and session persistence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import Settings, get_settings
from app.core.security import hash_password, new_session_token, verify_password
from app.db.schema import get_connection, migrate
from app.models.user import LOCAL_DEFAULT_USER_ID, UserPublic


class AuthStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        migrate(self._settings)

    def ensure_local_user(self) -> None:
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO users (user_id, email, password_hash, display_name, created_at)
                VALUES (?, NULL, NULL, 'Local Demo User', ?)
                """,
                (LOCAL_DEFAULT_USER_ID, _utc_now()),
            )

    def create_user(self, *, email: str, password: str, display_name: str) -> UserPublic:
        secret = _auth_secret(self._settings)
        user_id = email.lower().strip().replace("@", "_at_")
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, email, password_hash, display_name, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    email.lower(),
                    hash_password(password, secret=secret),
                    display_name or email,
                    _utc_now(),
                ),
            )
        return UserPublic(user_id=user_id, email=email.lower(), display_name=display_name or email)

    def authenticate(self, *, email: str, password: str) -> UserPublic | None:
        secret = _auth_secret(self._settings)
        with get_connection(self._settings) as conn:
            row = conn.execute(
                "SELECT user_id, email, password_hash, display_name FROM users WHERE email = ?",
                (email.lower(),),
            ).fetchone()
        if not row or not row["password_hash"]:
            return None
        if not verify_password(password, row["password_hash"], secret=secret):
            return None
        return UserPublic(
            user_id=row["user_id"],
            email=row["email"],
            display_name=row["display_name"],
        )

    def create_session(self, user_id: str) -> str:
        token = new_session_token()
        expires = datetime.now(timezone.utc) + timedelta(hours=self._settings.session_ttl_hours)
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT INTO sessions (token, user_id, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (token, user_id, expires.isoformat(), _utc_now()),
            )
        return token

    def resolve_token(self, token: str) -> UserPublic | None:
        if not token or not token.strip():
            return None
        now = datetime.now(timezone.utc).isoformat()
        with get_connection(self._settings) as conn:
            # Drop stale rows for this token so revoked/expired sessions do not linger.
            conn.execute(
                "DELETE FROM sessions WHERE token = ? AND expires_at <= ?",
                (token, now),
            )
            row = conn.execute(
                """
                SELECT s.user_id, u.email, u.display_name
                FROM sessions s
                JOIN users u ON u.user_id = s.user_id
                WHERE s.token = ? AND s.expires_at > ?
                """,
                (token, now),
            ).fetchone()
        if not row:
            return None
        return UserPublic(
            user_id=row["user_id"],
            email=row["email"],
            display_name=row["display_name"],
        )

    def revoke_session(self, token: str) -> bool:
        with get_connection(self._settings) as conn:
            cur = conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            return cur.rowcount > 0

    def revoke_all_sessions(self, user_id: str) -> int:
        with get_connection(self._settings) as conn:
            cur = conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            return int(cur.rowcount)


def _auth_secret(settings: Settings) -> str:
    import os

    secret = os.environ.get(settings.auth_secret_env, "")
    if not secret:
        if settings.local_demo_mode and not settings.auth_enabled:
            return "local-demo-not-for-production"
        raise RuntimeError(f"Missing {settings.auth_secret_env} for authentication")
    return secret


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
