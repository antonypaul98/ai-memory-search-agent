"""Selected OAuth vault persistence: real Postgres, encrypted, tenant-scoped, no SQLite fallback."""
from __future__ import annotations

import os
import sqlite3
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.db.postgres_runtime import PostgresConfigurationError, get_postgres_connection_factory
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.services.oauth_token_vault import OAuthTokenVault


def test_selected_oauth_vault_missing_dsn_never_opens_sqlite(monkeypatch, tmp_path):
    env_name = "P03_OAUTH_MISSING_DSN"
    monkeypatch.delenv(env_name, raising=False)
    attempts = []

    def reject(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("selected Postgres OAuth vault opened SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject)
    settings = Settings(
        _env_file=None,
        memory_store_backend="postgres",
        postgres_dsn_env=env_name,
        sqlite_path=str(tmp_path / "forbidden.db"),
    )
    with pytest.raises(PostgresConfigurationError):
        OAuthTokenVault(settings, event_bus=MagicMock(), fernet=Fernet(Fernet.generate_key()))
    assert attempts == []
    assert not (tmp_path / "forbidden.db").exists()


@pytest.fixture
def pg_oauth_vault(monkeypatch, tmp_path):
    if not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"):
        pytest.skip("real Postgres DSN required")
    settings = Settings(
        _env_file=None,
        **{field: "postgres" for field in RELATIONAL_STORE_BACKEND_FIELDS},
        postgres_dsn_env="MEMORY_AGENT_TEST_POSTGRES_DSN",
        sqlite_path=str(tmp_path / "forbidden.db"),
        jobs_enabled=False,
    )
    attempts = []

    def reject(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("selected Postgres OAuth vault opened SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject)
    nonce = uuid4().hex
    owner, other = f"oauth-owner-{nonce}", f"oauth-other-{nonce}"
    connector = f"provider-{nonce}"
    factory = get_postgres_connection_factory(settings)
    vault = OAuthTokenVault(
        settings,
        event_bus=MagicMock(),
        fernet=Fernet(Fernet.generate_key()),
    )
    try:
        yield settings, vault, factory, owner, other, connector
    finally:
        with factory() as conn:
            conn.execute(
                "DELETE FROM connector_oauth_tokens WHERE user_id IN (%s, %s)",
                (owner, other),
            )
        assert attempts == []
        assert not (tmp_path / "forbidden.db").exists()


def test_postgres_oauth_tokens_are_encrypted_and_tenant_isolated(pg_oauth_vault):
    settings, vault, factory, owner, other, connector = pg_oauth_vault
    vault.put(
        user_id=owner,
        connector_id=connector,
        access_token="access-secret-value",
        refresh_token="refresh-secret-value",
        scopes=["read", "write", "read"],
    )

    restarted = OAuthTokenVault(
        settings,
        event_bus=MagicMock(),
        fernet=vault._fernet,
    )
    record = restarted.get(user_id=owner, connector_id=connector, audit_use=False)
    assert record is not None
    assert record.access_token == "access-secret-value"
    assert record.refresh_token == "refresh-secret-value"
    assert record.scopes == ("read", "write")
    assert restarted.get(user_id=other, connector_id=connector, audit_use=False) is None

    with factory() as conn:
        raw = conn.execute(
            "SELECT encrypted_payload FROM connector_oauth_tokens WHERE user_id=%s AND connector_id=%s",
            (owner, connector),
        ).fetchone()
    ciphertext = bytes(raw["encrypted_payload"])
    assert b"access-secret-value" not in ciphertext
    assert b"refresh-secret-value" not in ciphertext


def test_postgres_oauth_revoke_is_exact_tenant_and_erases_credentials(pg_oauth_vault):
    _, vault, _, owner, other, connector = pg_oauth_vault
    vault.put(user_id=owner, connector_id=connector, access_token="secret")

    assert vault.revoke(user_id=other, connector_id=connector) is False
    assert vault.get(user_id=owner, connector_id=connector, audit_use=False) is not None
    assert vault.revoke(user_id=owner, connector_id=connector) is True
    assert vault.get(user_id=owner, connector_id=connector, audit_use=False) is None
    assert vault.revoke(user_id=owner, connector_id=connector) is False
