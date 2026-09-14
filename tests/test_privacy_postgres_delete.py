"""Real-Postgres acceptance for the PrivacyService destructive delete surface."""
from __future__ import annotations

import os
import sqlite3
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.memory_store_factory import get_memory_store
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.models.video import SourceType
from app.services.privacy_service import PrivacyService


def test_privacy_delete_complete_postgres_profile_never_opens_relational_sqlite(monkeypatch, tmp_path):
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
    store = get_memory_store(settings)
    owner_id = f"privacy-delete-{uuid4().hex}"
    neighbor_id = f"privacy-neighbor-{uuid4().hex}"
    owner = store.upsert(
        user_id=owner_id,
        source_type=SourceType.WEB,
        external_id=f"owner-{uuid4().hex}",
        canonical_url="https://example.com/privacy-owner",
        title="Privacy owner memory",
    )
    neighbor = store.upsert(
        user_id=neighbor_id,
        source_type=SourceType.WEB,
        external_id=f"neighbor-{uuid4().hex}",
        canonical_url="https://example.com/privacy-neighbor",
        title="Privacy neighboring tenant memory",
    )
    attempts: list[tuple[tuple, dict]] = []

    def reject(*args, **kwargs):
        attempts.append((args, kwargs))
        raise AssertionError("production privacy delete opened relational SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject)

    service = PrivacyService(settings)
    result = service.delete_memory(memory_id=owner.memory_id, user_id=owner_id)

    assert result["deleted"] is True
    assert result["memory_id"] == owner.memory_id
    assert store.get(owner.memory_id, user_id=owner_id) is None
    assert store.get(neighbor.memory_id, user_id=neighbor_id) is not None
    assert attempts == []
    assert not forbidden_db.exists()
