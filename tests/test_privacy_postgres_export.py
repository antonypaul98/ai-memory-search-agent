"""Real-Postgres acceptance for the PrivacyService export read surface."""
from __future__ import annotations

import os
import sqlite3
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.services.privacy_service import PrivacyService


def test_privacy_export_complete_postgres_profile_never_opens_relational_sqlite(monkeypatch, tmp_path):
    if not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"):
        pytest.skip("real Postgres DSN required")

    forbidden_db = tmp_path / "forbidden.db"
    settings = Settings(
        _env_file=None,
        **{field: "postgres" for field in RELATIONAL_STORE_BACKEND_FIELDS},
        postgres_dsn_env="MEMORY_AGENT_TEST_POSTGRES_DSN",
        sqlite_path=str(forbidden_db),
        jobs_enabled=False,
    )
    attempts: list[tuple[tuple, dict]] = []

    def reject(*args, **kwargs):
        attempts.append((args, kwargs))
        raise AssertionError("production privacy export opened relational SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject)

    user_id = f"privacy-export-{uuid4().hex}"
    service = PrivacyService(settings)
    payload = service.export_user_data(user_id=user_id)

    assert payload["user"]["user_id"] == user_id
    assert payload["memories"] == []
    assert payload["youtube_memories"] == []
    assert payload["captures"] == []
    assert payload["browser_bookmarks"] == []
    assert payload["jobs"] == []
    assert attempts == []
    assert not forbidden_db.exists()
