from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.db.schema import get_connection
from app.services.event_bus import EventBus
from app.services.oauth_token_vault import OAuthTokenVault


def _settings(tmp_path) -> Settings:
    return Settings(
        sqlite_path=str(tmp_path / "oauth.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        transcript_artifact_dir=str(tmp_path / "transcripts"),
        jobs_enabled=False,
    )


def _vault(tmp_path) -> tuple[OAuthTokenVault, Settings, EventBus]:
    settings = _settings(tmp_path)
    events = EventBus(settings)
    vault = OAuthTokenVault(settings, event_bus=events, fernet=Fernet(Fernet.generate_key()))
    return vault, settings, events


def test_tokens_are_encrypted_and_tenant_scoped(tmp_path):
    vault, settings, _ = _vault(tmp_path)
    expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    vault.put(
        user_id="alice",
        connector_id="gdrive.v1",
        access_token="alice-access-secret",
        refresh_token="alice-refresh-secret",
        scopes=["drive.readonly", "profile", "drive.readonly"],
        expires_at=expiry,
    )
    vault.put(
        user_id="bob",
        connector_id="gdrive.v1",
        access_token="bob-access-secret",
    )

    with get_connection(settings) as conn:
        raw = conn.execute(
            "SELECT encrypted_payload FROM connector_oauth_tokens WHERE user_id='alice'"
        ).fetchone()[0]
    assert b"alice-access-secret" not in bytes(raw)
    assert b"alice-refresh-secret" not in bytes(raw)

    alice = vault.get(user_id="alice", connector_id="gdrive.v1")
    bob = vault.get(user_id="bob", connector_id="gdrive.v1")
    assert alice is not None and alice.access_token == "alice-access-secret"
    assert alice.scopes == ("drive.readonly", "profile")
    assert bob is not None and bob.access_token == "bob-access-secret"
    assert vault.get(user_id="charlie", connector_id="gdrive.v1") is None


def test_token_use_is_audited_without_secret_material(tmp_path):
    vault, _, events = _vault(tmp_path)
    vault.put(
        user_id="alice",
        connector_id="gdrive.v1",
        access_token="audit-access-secret",
        refresh_token="audit-refresh-secret",
        scopes=["drive.readonly"],
    )

    record = vault.get(user_id="alice", connector_id="gdrive.v1")
    assert record is not None

    audit, _ = events.list_events(user_id="alice", event_type="connector.oauth.used")
    assert len(audit) == 1
    assert audit[0].aggregate_type == "connector"
    assert audit[0].aggregate_id == "gdrive.v1"
    serialized = str(audit[0].payload)
    assert "audit-access-secret" not in serialized
    assert "audit-refresh-secret" not in serialized


def test_expired_token_refreshes_once_and_persists_rotation(tmp_path):
    vault, _, events = _vault(tmp_path)
    vault.put(
        user_id="alice",
        connector_id="gdrive.v1",
        access_token="expired",
        refresh_token="refresh-1",
        scopes=["drive.readonly"],
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    calls = []

    def refresh(record):
        calls.append(record.refresh_token)
        return {"access_token": "fresh-access", "refresh_token": "refresh-2", "expires_in": 3600}

    record = vault.get_valid(user_id="alice", connector_id="gdrive.v1", refresh=refresh)
    assert calls == ["refresh-1"]
    assert record.access_token == "fresh-access"
    assert record.refresh_token == "refresh-2"
    assert not record.expired

    again = vault.get_valid(user_id="alice", connector_id="gdrive.v1", refresh=refresh)
    assert again.access_token == "fresh-access"
    assert calls == ["refresh-1"]

    audit, _ = events.list_events(user_id="alice", event_type="connector.oauth.refreshed")
    assert len(audit) == 1
    assert audit[0].aggregate_id == "gdrive.v1"
    assert "fresh-access" not in str(audit[0].payload)
    assert "refresh-2" not in str(audit[0].payload)


def test_revoke_disables_connector_and_erases_retrievable_token(tmp_path):
    vault, settings, events = _vault(tmp_path)
    vault.put(user_id="alice", connector_id="notion.v1", access_token="secret")

    assert vault.revoke(user_id="alice", connector_id="notion.v1") is True
    assert vault.get(user_id="alice", connector_id="notion.v1") is None
    assert vault.revoke(user_id="alice", connector_id="notion.v1") is False

    with get_connection(settings) as conn:
        row = conn.execute(
            "SELECT enabled, encrypted_payload FROM connector_oauth_tokens WHERE user_id=? AND connector_id=?",
            ("alice", "notion.v1"),
        ).fetchone()
    assert row["enabled"] == 0
    assert b"secret" not in bytes(row["encrypted_payload"])

    audit, _ = events.list_events(user_id="alice", event_type="connector.oauth.revoked")
    assert len(audit) == 1


def test_missing_encryption_key_fails_closed(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.delenv(settings.connector_token_key_env, raising=False)
    with pytest.raises(RuntimeError, match="requires encryption key"):
        OAuthTokenVault(settings)


def test_refresh_failure_does_not_replace_existing_token(tmp_path):
    vault, _, events = _vault(tmp_path)
    vault.put(
        user_id="alice",
        connector_id="readwise.v1",
        access_token="expired-access",
        refresh_token="refresh-token",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )

    with pytest.raises(RuntimeError, match="did not return an access token"):
        vault.get_valid(
            user_id="alice",
            connector_id="readwise.v1",
            refresh=lambda _: {"expires_in": 3600},
        )

    existing = vault.get(user_id="alice", connector_id="readwise.v1", audit_use=False)
    assert existing is not None and existing.access_token == "expired-access"
    audit, _ = events.list_events(user_id="alice", event_type="connector.oauth.refresh_failed")
    assert len(audit) == 1
