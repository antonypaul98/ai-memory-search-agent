"""Tests for Phase 1 operator CLI utilities (F-28)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.config import Settings
from scripts import ingest_item, reset_db


def test_reset_local_data_dry_run_and_delete(tmp_path) -> None:
    sqlite = tmp_path / "videos.db"
    sqlite.write_text("db", encoding="utf-8")
    (tmp_path / "videos.db-wal").write_text("wal", encoding="utf-8")
    chroma = tmp_path / "chroma"
    chroma.mkdir()
    (chroma / "index.bin").write_text("x", encoding="utf-8")
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    (transcripts / "item.json").write_text("{}", encoding="utf-8")

    settings = Settings(
        sqlite_path=str(sqlite),
        chroma_persist_dir=str(chroma),
        transcript_artifact_dir=str(transcripts),
    )

    found = reset_db.reset_local_data(settings, dry_run=True)
    assert sqlite.resolve() in found
    assert chroma.resolve() in found
    assert transcripts.resolve() in found
    assert sqlite.exists()

    removed = reset_db.reset_local_data(settings)
    assert sqlite.resolve() in removed
    assert not sqlite.exists()
    assert not (tmp_path / "videos.db-wal").exists()
    assert not chroma.exists()
    assert not transcripts.exists()


def test_reset_refuses_unsafe_target(monkeypatch) -> None:
    settings = Settings(sqlite_path="/", chroma_persist_dir="/", transcript_artifact_dir="/")
    with pytest.raises(ValueError):
        reset_db.reset_local_data(settings, dry_run=True)


def test_reset_cli_requires_explicit_yes(tmp_path, monkeypatch, capsys) -> None:
    sqlite = tmp_path / "videos.db"
    sqlite.write_text("db", encoding="utf-8")
    settings = Settings(
        sqlite_path=str(sqlite),
        chroma_persist_dir=str(tmp_path / "chroma"),
        transcript_artifact_dir=str(tmp_path / "transcripts"),
    )
    monkeypatch.setattr(reset_db, "get_settings", lambda: settings)

    assert reset_db.main([]) == 2
    assert sqlite.exists()
    assert "Nothing deleted" in capsys.readouterr().out


def test_ingest_item_cli_success(monkeypatch, capsys) -> None:
    calls: dict[str, object] = {}

    class FakeService:
        def ingest_single_url(self, url, *, user_id=None, force_refresh=False):
            calls.update(url=url, user_id=user_id, force_refresh=force_refresh)
            return SimpleNamespace(
                model_dump=lambda: {
                    "success": True,
                    "skipped": False,
                    "video_id": "abc123",
                    "title": "Demo",
                }
            )

    monkeypatch.setattr(ingest_item, "IngestService", FakeService)
    code = ingest_item.main(
        ["https://www.youtube.com/watch?v=abc123", "--force-refresh", "--user-id", "u1"]
    )

    assert code == 0
    assert calls == {
        "url": "https://www.youtube.com/watch?v=abc123",
        "user_id": "u1",
        "force_refresh": True,
    }
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    assert payload["video_id"] == "abc123"


def test_ingest_item_cli_failure_exit(monkeypatch, capsys) -> None:
    class FakeService:
        def ingest_single_url(self, url, *, user_id=None, force_refresh=False):
            return SimpleNamespace(model_dump=lambda: {"success": False, "error": "boom"})

    monkeypatch.setattr(ingest_item, "IngestService", FakeService)
    assert ingest_item.main(["https://youtu.be/abc123"]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "boom"


def test_ingest_item_cli_exception_is_structured(monkeypatch, capsys) -> None:
    class FakeService:
        def ingest_single_url(self, url, *, user_id=None, force_refresh=False):
            raise RuntimeError("network unavailable")

    monkeypatch.setattr(ingest_item, "IngestService", FakeService)
    assert ingest_item.main(["https://youtu.be/abc123"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"success": False, "error": "network unavailable"}
