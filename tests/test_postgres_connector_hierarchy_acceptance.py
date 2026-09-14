"""Real generic PDF ingest, hierarchical retrieval and retry on Postgres/Chroma."""
import json
import os
import sqlite3
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
from app.models.video import SourceType
from app.services.connector_ingest_service import ConnectorIngestService
from app.services.ahme_engine import AdaptiveHierarchicalMemoryEngine


def test_generic_postgres_hierarchy_is_owned_and_retry_safe(monkeypatch, tmp_path):
    if not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"):
        pytest.skip("real Postgres DSN required")
    settings = Settings(
        _env_file=None,
        **{field: "postgres" for field in RELATIONAL_STORE_BACKEND_FIELDS},
        postgres_dsn_env="MEMORY_AGENT_TEST_POSTGRES_DSN",
        sqlite_path=str(tmp_path / "forbidden.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        hierarchical_retrieval_enabled=True, semantic_cache_enabled=False,
        llm_provider="none", jobs_enabled=False,
    )
    attempts = []
    def reject_sqlite(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("unexpected relational SQLite connection")
    monkeypatch.setattr(sqlite3, "connect", reject_sqlite)
    monkeypatch.setattr("app.services.connector_ingest_service.embed_texts",
                        lambda texts, settings=None: [[1.0, 0.0, 0.0] for _ in texts])
    monkeypatch.setattr("app.services.ahme_engine.embed_query",
                        lambda *args, **kwargs: [1.0, 0.0, 0.0])
    service = ConnectorIngestService(settings)
    owner, other = "pdf-" + uuid4().hex, "pdf-" + uuid4().hex
    external_id = "pdf-" + uuid4().hex
    url = "pdf://" + external_id
    def ingest(tenant, marker):
        return service.ingest_url(
            url, user_id=tenant, connector_id="pdf.v1", force_refresh=True,
            ref_extra={"filename": marker + ".pdf", "pages_text": [
                marker + " Postgres transactions preserve canonical evidence and tenant isolation."
            ]},
        )
    for tenant, marker in ((owner, "owneralpha"), (other, "ownerbeta")):
        result = ingest(tenant, marker)
        # Do not echo error payloads which could contain driver connection details.
        assert result.success
        assert result.chunk_count > 0
        memory = service._memory_os._store.get_by_external(
            source_type=SourceType.PDF, external_id=external_id, user_id=tenant,
        )
        assert memory is not None
    engine = AdaptiveHierarchicalMemoryEngine(settings=settings)
    for tenant, marker, excluded in ((owner, "owneralpha", "ownerbeta"), (other, "ownerbeta", "owneralpha")):
        hits, metrics = engine.retrieve(marker, user_id=tenant)
        assert metrics.pipeline == "hierarchical"
        assert hits
        assert excluded not in json.dumps(hits)
        for name in (settings.capsule_collection_name, settings.section_collection_name):
            rows = service._hstore._collection(name).get(where={"user_id": tenant}, include=["metadatas"])
            assert rows["ids"]
            assert all(meta["user_id"] == tenant for meta in rows["metadatas"])
    before = service._hstore.count_vectors()
    original_upsert = service._hstore.upsert_sections
    with monkeypatch.context() as patch:
        def fail(*args, **kwargs):
            raise RuntimeError("injected section write failure")
        patch.setattr(service._hstore, "upsert_sections", fail)
        assert not ingest(owner, "owneralpha").success
    assert ingest(owner, "owneralpha").success
    assert service._hstore.count_vectors() == before
    other_hits, metrics = engine.retrieve("ownerbeta", user_id=other)
    assert other_hits and metrics.pipeline == "hierarchical"
    assert "owneralpha" not in json.dumps(other_hits)
    empty, _ = engine.retrieve("owneralpha", user_id="unrelated-" + uuid4().hex)
    assert empty == []
    assert attempts == []
    assert not (tmp_path / "forbidden.db").exists()
