from pathlib import Path


def test_ingest_service_routes_artifacts_through_selected_store() -> None:
    source = Path("app/services/ingest_service.py").read_text(encoding="utf-8")

    assert "get_ingest_artifact_store" in source
    assert "self._artifact_store = get_ingest_artifact_store(self._settings)" in source
    assert "self._artifact_store.transcript_unchanged(" in source
    assert "self._artifact_store.store_capsule_json(" in source
    assert "self._artifact_store.store_transcript_hash(" in source

    # Every artifact operation must carry explicit tenant identity.
    for marker in (
        "self._artifact_store.transcript_unchanged(",
        "self._artifact_store.store_capsule_json(",
        "self._artifact_store.store_transcript_hash(",
    ):
        call = source.split(marker, 1)[1].split(")", 1)[0]
        assert "user_id=owner_id" in call
        assert "video_id=" in call

    # The ingestion runtime must not retain the direct legacy SQLite helpers.
    assert "store_capsule_json(self._settings" not in source
    assert "_transcript_unchanged(" not in source
    assert "_store_transcript_hash(" not in source
    assert "get_connection(settings)" not in source
