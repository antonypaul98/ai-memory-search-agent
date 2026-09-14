from pathlib import Path


def test_ingest_hierarchical_vector_calls_are_tenant_scoped():
    source = Path("app/services/ingest_service.py").read_text(encoding="utf-8")

    assert "self._hstore.delete_video(metadata.video_id, user_id=owner_id)" in source
    assert "self._hstore.upsert_capsule(capsule, capsule_emb, user_id=owner_id)" in source
    assert "metadata.video_id, capsule.sections, section_embs, user_id=owner_id" in source
