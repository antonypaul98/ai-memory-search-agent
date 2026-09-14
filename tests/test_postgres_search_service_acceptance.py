"""Real SearchService/Chroma with selected Postgres relational stores.

Only the external embedding API is deterministic; this exercises the supported
flat evidence path. Hierarchical vector tenant isolation is a separate gate.
"""
import os
import sqlite3
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.postgres_runtime import PostgresConfigurationError
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.services.search_service import SearchService
from app.utils.chunking import TranscriptChunk


def test_search_youtube_selection_fails_closed_without_dsn(monkeypatch, tmp_path):
    monkeypatch.delenv('P03_SEARCH_MISSING_DSN', raising=False)
    attempts = []

    def reject(*args, **kwargs):
        attempts.append(True)
        raise AssertionError('unexpected relational SQLite connection')

    monkeypatch.setattr(sqlite3, 'connect', reject)
    settings = Settings(_env_file=None, youtube_store_backend='postgres',
                        postgres_dsn_env='P03_SEARCH_MISSING_DSN',
                        sqlite_path=str(tmp_path / 'forbidden.db'))
    with pytest.raises(PostgresConfigurationError):
        SearchService(settings, repository=MagicMock(), registry=MagicMock(), memory_store=MagicMock())
    assert attempts == []


def test_real_search_service_postgres_tenants_and_telemetry(monkeypatch, tmp_path):
    if not os.getenv('MEMORY_AGENT_TEST_POSTGRES_DSN'):
        pytest.skip('real Postgres DSN required')
    settings = Settings(
        _env_file=None,
        **{field: 'postgres' for field in RELATIONAL_STORE_BACKEND_FIELDS},
        postgres_dsn_env='MEMORY_AGENT_TEST_POSTGRES_DSN',
        sqlite_path=str(tmp_path / 'forbidden.db'),
        chroma_persist_dir=str(tmp_path / 'chroma'),
        hierarchical_retrieval_enabled=False, jobs_enabled=False,
    )
    attempts = []

    def reject(*args, **kwargs):
        attempts.append(True)
        raise AssertionError('unexpected relational SQLite connection')

    monkeypatch.setattr(sqlite3, 'connect', reject)
    monkeypatch.setattr('app.services.ahme_engine.embed_query', lambda *a, **k: [1.0, 0.0, 0.0])
    service = SearchService(settings)
    from app.db.memory_store_factory import get_memory_store as selected_store
    assert service._memory_store is selected_store(settings)
    owner, other = 'search-' + uuid4().hex, 'search-' + uuid4().hex
    for user_id, title in ((owner, 'Owner evidence'), (other, 'Other evidence')):
        service._repository.upsert_chunks(
            user_id=user_id, video_id='shared', url='https://example.test/shared',
            title=title, channel='fixture', thumbnail='', duration=10,
            transcript_source='fixture', chunks=[TranscriptChunk(0, title, 0.0, 5.0)],
            embeddings=[[1.0, 0.0, 0.0]], embedding_model='acceptance',
        )
        service._registry.upsert_video(user_id=user_id, video_id='shared',
                                      url='https://example.test/shared', title=title, channel='fixture')
    for user_id, title in ((owner, 'Owner evidence'), (other, 'Other evidence')):
        response = service.search('evidence', user_id=user_id)
        assert [item.title for item in response.results] == [title]
        assert service._registry.get_usage('shared', user_id=user_id).search_count == 1
        assert service._yt_store.diagnostics(user_id=user_id).average_search_latency_ms > 0
    assert service.search('evidence', user_id='unrelated-' + uuid4().hex).results == []
    assert attempts == []
    assert not (tmp_path / 'forbidden.db').exists()


def test_legacy_canonical_helper_fails_closed_without_dsn(monkeypatch, tmp_path):
    from app.db.memory_store import get_memory_store
    monkeypatch.delenv('P03_CANONICAL_MISSING_DSN', raising=False)
    attempts = []

    def reject(*args, **kwargs):
        attempts.append(True)
        raise AssertionError('unexpected relational SQLite connection')

    monkeypatch.setattr(sqlite3, 'connect', reject)
    settings = Settings(_env_file=None, memory_store_backend='postgres',
                        postgres_dsn_env='P03_CANONICAL_MISSING_DSN',
                        sqlite_path=str(tmp_path / 'forbidden.db'))
    with pytest.raises(PostgresConfigurationError):
        get_memory_store(settings)
    assert attempts == []
