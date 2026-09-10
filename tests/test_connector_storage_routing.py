"""Exercise generic ingest storage routing without replacing the ingest method."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.services import connector_ingest_service as module


def _dependencies(monkeypatch):
    dependencies = {}
    for name in ('MemoryRepository', 'get_video_registry', 'HierarchicalStore',
                 'UniversalMemoryService', 'CrossConnectorDuplicateDetector'):
        instance = MagicMock()
        monkeypatch.setattr(module, name, MagicMock(return_value=instance))
        dependencies[name] = instance
    dependencies['MemoryRepository'].upsert_chunks.return_value = 1
    dependencies['CrossConnectorDuplicateDetector'].check.return_value = SimpleNamespace(is_duplicate=False)
    dependencies['UniversalMemoryService'].finalize_ingest.return_value = SimpleNamespace(memory_id='canonical-id')
    return dependencies


@pytest.mark.parametrize('tenant', ['tenant-a', 'tenant-b'])
@pytest.mark.parametrize('hierarchy', [True, False])
def test_generic_ingest_uses_selected_stores_with_exact_tenant(tmp_path, monkeypatch, tenant, hierarchy):
    deps = _dependencies(monkeypatch)
    settings = Settings(sqlite_path=str(tmp_path / 'must-not-exist.db'),
                        fts_store_backend='postgres', youtube_store_backend='postgres',
                        semantic_cache_store_backend='postgres', hierarchical_retrieval_enabled=hierarchy)
    fts, artifacts, cache = MagicMock(), MagicMock(), MagicMock()
    fts_factory = MagicMock(return_value=fts)
    artifact_factory = MagicMock(return_value=artifacts)
    cache_factory = MagicMock(return_value=cache)
    monkeypatch.setattr(module, 'get_fts_index', fts_factory)
    monkeypatch.setattr(module, 'get_ingest_artifact_store', artifact_factory)
    monkeypatch.setattr(module, 'SemanticCache', cache_factory)
    monkeypatch.setattr(module, 'embed_texts', lambda texts, settings=None: [[0.1, 0.2] for _ in texts])
    service = module.ConnectorIngestService(settings)
    result = service.ingest_url('pdf://shared-doc', user_id=tenant, connector_id='pdf.v1',
                                ref_extra={'filename': 'guide.pdf', 'pages_text': [
                                    'Postgres transactions preserve canonical evidence and tenant isolation.'
                                ]})
    assert result.success, result.error
    fts_factory.assert_called_once_with(settings)
    artifact_factory.assert_called_once_with(settings)
    fts.delete_video.assert_called_once_with('shared-doc', user_id=tenant)
    if hierarchy:
        assert {c.kwargs['level'] for c in fts.upsert.call_args_list} == {'capsule', 'section', 'evidence'}
        assert all(c.kwargs['user_id'] == tenant for c in fts.upsert.call_args_list)
        artifacts.store_capsule_json.assert_called_once()
        payload = artifacts.store_capsule_json.call_args.kwargs
        assert (payload['user_id'], payload['video_id']) == (tenant, 'shared-doc')
        assert 'shared-doc' in payload['capsule_json']
    else:
        fts.upsert.assert_not_called()
        artifacts.store_capsule_json.assert_not_called()
    cache_factory.assert_called_once_with(settings)
    cache.bump_index_version_and_invalidate.assert_called_once_with()
    canonical = deps['UniversalMemoryService'].finalize_ingest.call_args.kwargs
    assert canonical['user_id'] == tenant
    assert canonical['metadata'].connector_id == 'pdf.v1'
    assert canonical['metadata'].webpage_url == 'pdf://shared-doc'
    registration = deps['CrossConnectorDuplicateDetector'].register.call_args.kwargs
    assert registration['user_id'] == tenant
    assert registration['memory_id'] == 'canonical-id'
    assert not (tmp_path / 'must-not-exist.db').exists()


def test_generic_ingest_refuses_authenticated_legacy_fts(tmp_path, monkeypatch):
    _dependencies(monkeypatch)
    settings = Settings(sqlite_path=str(tmp_path / 'must-not-exist.db'), auth_enabled=True,
                        fts_store_backend='sqlite')
    with pytest.raises(RuntimeError, match='Authenticated lexical search requires'):
        module.ConnectorIngestService(settings)
    assert not (tmp_path / 'must-not-exist.db').exists()


def test_generic_ingest_selected_postgres_failure_never_falls_back(tmp_path, monkeypatch):
    _dependencies(monkeypatch)
    from app.services.fts_index_factory import reset_fts_index_factory_cache
    reset_fts_index_factory_cache()
    settings = Settings(sqlite_path=str(tmp_path / 'must-not-exist.db'), fts_store_backend='postgres',
                        postgres_dsn_env='P03_MISSING_TEST_DSN')
    monkeypatch.delenv('P03_MISSING_TEST_DSN', raising=False)
    with pytest.raises(RuntimeError, match='P03_MISSING_TEST_DSN'):
        module.ConnectorIngestService(settings)
    assert not (tmp_path / 'must-not-exist.db').exists()
