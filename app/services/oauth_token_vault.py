"""Encrypted, tenant-scoped OAuth credential storage for connectors.

C-02 deliberately keeps provider-specific authorization flows out of the core. This
module provides the shared security primitives they need: encrypted-at-rest token
storage, refresh coordination, revocation state, and durable audit events.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings, get_settings
from app.db.schema import get_connection
from app.services.event_bus import EventBus


@dataclass(frozen=True)
class OAuthTokenRecord:
    user_id: str
    connector_id: str
    access_token: str
    refresh_token: str
    scopes: tuple[str, ...]
    expires_at: datetime | None
    enabled: bool

    @property
    def expired(self) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at <= datetime.now(timezone.utc)


RefreshCallback = Callable[[OAuthTokenRecord], dict[str, object]]


class OAuthTokenVault:
    """Store connector OAuth tokens encrypted with an environment-provided key."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        event_bus: EventBus | None = None,
        fernet: Fernet | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._events = event_bus or EventBus(self._settings)
        self._fernet = fernet or Fernet(self._load_key())
        self._ensure_table()

    def _load_key(self) -> bytes:
        env_name = self._settings.connector_token_key_env
        raw = os.getenv(env_name, "").strip()
        if not raw:
            raise RuntimeError(
                f"OAuth token storage requires encryption key environment variable {env_name}"
            )
        return raw.encode("utf-8")

    def _ensure_table(self) -> None:
        with get_connection(self._settings) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS connector_oauth_tokens (
                    user_id TEXT NOT NULL,
                    connector_id TEXT NOT NULL,
                    encrypted_payload BLOB NOT NULL,
                    scopes_json TEXT NOT NULL DEFAULT '[]',
                    expires_at TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, connector_id)
                );
                CREATE INDEX IF NOT EXISTS idx_connector_oauth_enabled
                    ON connector_oauth_tokens(user_id, enabled, connector_id);
                """
            )

    def put(
        self,
        *,
        user_id: str,
        connector_id: str,
        access_token: str,
        refresh_token: str = "",
        scopes: list[str] | tuple[str, ...] = (),
        expires_at: datetime | None = None,
    ) -> None:
        user_id, connector_id = self._validate_identity(user_id, connector_id)
        if not access_token.strip():
            raise ValueError("access_token is required")
        normalized_scopes = tuple(sorted({s.strip() for s in scopes if s and s.strip()}))
        payload = json.dumps(
            {"access_token": access_token, "refresh_token": refresh_token},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        encrypted = self._fernet.encrypt(payload)
        now = datetime.now(timezone.utc).isoformat()
        expiry = expires_at.astimezone(timezone.utc).isoformat() if expires_at else None
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT INTO connector_oauth_tokens (
                    user_id, connector_id, encrypted_payload, scopes_json,
                    expires_at, enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(user_id, connector_id) DO UPDATE SET
                    encrypted_payload=excluded.encrypted_payload,
                    scopes_json=excluded.scopes_json,
                    expires_at=excluded.expires_at,
                    enabled=1,
                    updated_at=excluded.updated_at
                """,
                (
                    user_id,
                    connector_id,
                    encrypted,
                    json.dumps(normalized_scopes),
                    expiry,
                    now,
                    now,
                ),
            )
        self._audit(user_id, connector_id, "connector.oauth.stored", {"scopes": len(normalized_scopes)})

    def get(self, *, user_id: str, connector_id: str, audit_use: bool = True) -> OAuthTokenRecord | None:
        user_id, connector_id = self._validate_identity(user_id, connector_id)
        with get_connection(self._settings) as conn:
            row = conn.execute(
                """
                SELECT encrypted_payload, scopes_json, expires_at, enabled
                FROM connector_oauth_tokens
                WHERE user_id=? AND connector_id=?
                """,
                (user_id, connector_id),
            ).fetchone()
        if not row:
            return None
        if not bool(row["enabled"]):
            return None
        try:
            decoded = json.loads(self._fernet.decrypt(bytes(row["encrypted_payload"])).decode("utf-8"))
        except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("stored OAuth token cannot be decrypted") from exc
        expires_at = datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None
        record = OAuthTokenRecord(
            user_id=user_id,
            connector_id=connector_id,
            access_token=str(decoded.get("access_token") or ""),
            refresh_token=str(decoded.get("refresh_token") or ""),
            scopes=tuple(json.loads(row["scopes_json"] or "[]")),
            expires_at=expires_at,
            enabled=True,
        )
        if audit_use:
            self._audit(user_id, connector_id, "connector.oauth.used", {"expired": record.expired})
        return record

    def get_valid(
        self,
        *,
        user_id: str,
        connector_id: str,
        refresh: RefreshCallback,
        refresh_skew_sec: int = 60,
    ) -> OAuthTokenRecord:
        """Return a usable token, refreshing once when expired or near expiry."""
        if refresh_skew_sec < 0 or refresh_skew_sec > 3600:
            raise ValueError("refresh_skew_sec must be between 0 and 3600")
        record = self.get(user_id=user_id, connector_id=connector_id)
        if record is None:
            raise LookupError("connector is not connected")
        now = datetime.now(timezone.utc)
        needs_refresh = record.expires_at is not None and record.expires_at <= now + timedelta(seconds=refresh_skew_sec)
        if not needs_refresh:
            return record
        if not record.refresh_token:
            self._audit(user_id, connector_id, "connector.oauth.refresh_failed", {"reason": "missing_refresh_token"})
            raise RuntimeError("OAuth token expired and no refresh token is available")

        result = refresh(record)
        access_token = str(result.get("access_token") or "").strip()
        if not access_token:
            self._audit(user_id, connector_id, "connector.oauth.refresh_failed", {"reason": "invalid_response"})
            raise RuntimeError("OAuth refresh did not return an access token")
        refresh_token = str(result.get("refresh_token") or record.refresh_token)
        expires_in = result.get("expires_in")
        expires_at = None
        if expires_in is not None:
            expires_at = now + timedelta(seconds=max(0, int(expires_in)))
        elif record.expires_at is not None:
            expires_at = now + timedelta(hours=1)
        self.put(
            user_id=user_id,
            connector_id=connector_id,
            access_token=access_token,
            refresh_token=refresh_token,
            scopes=record.scopes,
            expires_at=expires_at,
        )
        self._audit(user_id, connector_id, "connector.oauth.refreshed", {})
        refreshed = self.get(user_id=user_id, connector_id=connector_id, audit_use=False)
        assert refreshed is not None
        return refreshed

    def revoke(self, *, user_id: str, connector_id: str) -> bool:
        """Disable and cryptographically erase stored credentials for one tenant."""
        user_id, connector_id = self._validate_identity(user_id, connector_id)
        tombstone = self._fernet.encrypt(b'{}')
        with get_connection(self._settings) as conn:
            cur = conn.execute(
                """
                UPDATE connector_oauth_tokens
                SET encrypted_payload=?, enabled=0, expires_at=NULL, updated_at=?
                WHERE user_id=? AND connector_id=? AND enabled=1
                """,
                (tombstone, datetime.now(timezone.utc).isoformat(), user_id, connector_id),
            )
        changed = cur.rowcount > 0
        if changed:
            self._audit(user_id, connector_id, "connector.oauth.revoked", {})
        return changed

    @staticmethod
    def _validate_identity(user_id: str, connector_id: str) -> tuple[str, str]:
        user_id = (user_id or "").strip()
        connector_id = (connector_id or "").strip()
        if not user_id:
            raise ValueError("user_id is required")
        if not connector_id or len(connector_id) > 120:
            raise ValueError("valid connector_id is required")
        return user_id, connector_id

    def _audit(self, user_id: str, connector_id: str, event_type: str, payload: dict[str, object]) -> None:
        self._events.emit(
            user_id=user_id,
            event_type=event_type,
            aggregate_type="connector",
            aggregate_id=connector_id,
            actor="oauth-vault",
            payload=payload,
        )
