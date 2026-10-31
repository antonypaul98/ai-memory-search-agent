"""Synthetic consent grant/revoke HTTP and SQL boundary tests; no camera use."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.auth import get_current_user
from app.api.routes.home_agent_identity_consent import get_identity_consent_store
from app.config import get_settings
from app.db.postgres_home_image_store import PostgresHomeImageStore
from app.models.user import UserPublic


EXPIRY = datetime(2026, 10, 26, 6, 0, tzinfo=timezone.utc)


class ConsentStore:
    def __init__(self):
        self.grants = []
        self.revokes = []

    def grant_instance_identity_consent(self, **kwargs):
        self.grants.append(kwargs)
        return EXPIRY

    def revoke_instance_identity_consent(self, **kwargs):
        self.revokes.append(kwargs)
        return 2


def _post(test_settings, store, path, body, *, bearer=True, enabled=True):
    from app.main import app

    # The test overrides identity resolution, not the explicit bearer gate.
    # Production get_current_user separately verifies the supplied token.
    app.dependency_overrides[get_current_user] = lambda: UserPublic(user_id="house-a")
    app.dependency_overrides[get_identity_consent_store] = lambda: store
    app.dependency_overrides[get_settings] = lambda: SimpleNamespace(auth_enabled=enabled)
    headers = {"Authorization": "Bearer synthetic-token"} if bearer else {}
    try:
        with patch("app.main.get_settings", lambda: test_settings):
            with TestClient(app) as client:
                return client.post("/api/v1/home-agent/" + path, json=body, headers=headers)
    finally:
        app.dependency_overrides.clear()


def test_explicit_bearer_grant_uses_authenticated_tenant(test_settings):
    store = ConsentStore()
    response = _post(test_settings, store, "identity-consent/grant",
                     {"source_id": "camera-a", "ttl_seconds": 180})
    assert response.status_code == 200
    assert response.json() == {
        "source_id": "camera-a", "expires_at": "2026-10-26T06:00:00Z",
    }
    assert store.grants == [{
        "user_id": "house-a", "source_id": "camera-a", "ttl_seconds": 180,
    }]


def test_revoke_erases_identity_links_only_for_authenticated_source(test_settings):
    store = ConsentStore()
    response = _post(test_settings, store, "identity-consent/revoke",
                     {"source_id": "camera-b"})
    assert response.status_code == 200
    assert response.json() == {"erased_associations": 2}
    assert store.revokes == [{"user_id": "house-a", "source_id": "camera-b"}]


@pytest.mark.parametrize("bearer,enabled", [(False, True), (True, False), (False, False)])
def test_no_ambient_cookie_or_disabled_auth_consent(test_settings, bearer, enabled):
    store = ConsentStore()
    for path in ("identity-consent/grant", "identity-consent/revoke"):
        response = _post(test_settings, store, path, {"source_id": "camera-a"},
                         bearer=bearer, enabled=enabled)
        assert response.status_code == 403
    assert store.grants == []
    assert store.revokes == []


@pytest.mark.parametrize("body", [
    {"source_id": "camera-a", "user_id": "house-b"},
    {"source_id": "camera-a", "instance_id": "keys-1"},
    {"source_id": "camera-a", "ttl_seconds": 3601},
    {"source_id": "camera-a", "ttl_seconds": 0},
    {"source_id": "camera-a", "ttl_seconds": True},
    {"source_id": "camera-a", "ttl_seconds": 1.5},
    {"source_id": ""},
    {"source_id": "   "},
])
def test_grant_rejects_tenant_identity_spoof_and_invalid_bounds(test_settings, body):
    store = ConsentStore()
    response = _post(test_settings, store, "identity-consent/grant", body)
    assert response.status_code == 422
    assert store.grants == []


def test_grant_normalizes_source_without_client_controlled_tenant(test_settings):
    store = ConsentStore()
    response = _post(test_settings, store, "identity-consent/grant",
                     {"source_id": " camera-a "})
    assert response.status_code == 200
    assert response.json()["source_id"] == "camera-a"
    assert store.grants == [{
        "user_id": "house-a", "source_id": "camera-a", "ttl_seconds": 300,
    }]


def test_revoke_rejects_client_selected_tenant(test_settings):
    store = ConsentStore()
    response = _post(test_settings, store, "identity-consent/revoke",
                     {"source_id": "camera-a", "user_id": "house-b"})
    assert response.status_code == 422
    assert store.revokes == []


class Cursor:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class Connection:
    def __init__(self, statements, *, fenced=False):
        self.statements = statements
        self.fenced = fenced

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.statements.append((normalized, params))
        if "FROM pg_class" in normalized:
            return Cursor({"exists": 1} if self.fenced else None)
        if "FROM account_erasure_fences" in normalized:
            return Cursor({"fenced": 1} if self.fenced else None)
        if "RETURNING expires_at" in normalized:
            return Cursor({"expires_at": EXPIRY})
        return Cursor()


def _store(*, fenced=False):
    statements = []
    store = PostgresHomeImageStore(
        lambda: Connection(statements, fenced=fenced),
    )
    return store, statements


def test_grant_sql_uses_database_time_tenant_fence_and_bounded_upsert():
    store, statements = _store()
    assert store.grant_instance_identity_consent(
        user_id="house-a", source_id="camera-a", ttl_seconds=180,
    ) == EXPIRY
    sql = "\n".join(statement for statement, _ in statements)
    assert "pg_advisory_xact_lock_shared" in sql
    assert "CURRENT_TIMESTAMP + (%s * INTERVAL '1 second')" in sql
    assert "ON CONFLICT (user_id, source_id) DO UPDATE" in sql
    assert "revoked_at = NULL" in sql
    assert sql.index("pg_advisory_xact_lock_shared") < sql.index("RETURNING expires_at")
    insert = next((statement, params) for statement, params in statements
                  if "INSERT INTO home_instance_identity_consents" in statement)
    assert insert[1] == ("house-a", "camera-a", 180)


@pytest.mark.parametrize("ttl", [0, 3601, True, 1.5, "300", None])
def test_bad_grant_ttl_rejected_before_database_write(ttl):
    store, statements = _store()
    before = len(statements)
    with pytest.raises(ValueError):
        store.grant_instance_identity_consent(
            user_id="house-a", source_id="camera-a", ttl_seconds=ttl,
        )
    assert len(statements) == before


def test_erasure_fence_prevents_new_grants():
    store, statements = _store(fenced=True)
    with pytest.raises(PermissionError):
        store.grant_instance_identity_consent(
            user_id="house-a", source_id="camera-a",
        )
    assert not any("INSERT INTO home_instance_identity_consents" in sql
                   for sql, _ in statements)
