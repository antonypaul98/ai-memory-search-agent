"""Regression coverage for the operator CLI utilities (F-28)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import ingest_item, reset_db


class _Result:
    def __init__(self, *, success: bool, marker: str = "") -> None:
        self.success = success
        self.marker = marker

    def model_dump(self) -> dict:
        return {"success": self.success, "marker": self.marker}


def test_ingest_item_forwards_user_and_force_refresh(monkeypatch, capsys) -> None:
    calls: list[tuple[str, str | None, bool]] = []

    class FakeIngestService:
        def ingest_single_url(self, url: str, *, user_id=None, force_refresh=False):
            calls.append((url, user_id, force_refresh))
            return _Result(success=True, marker="indexed")

    monkeypatch.setattr(ingest_item, "IngestService", FakeIngestService)

    code = ingest_item.main(
        ["https://www.youtube.com/watch?v=test123", "--force-refresh", "--user-id", "u-1"]
    )

    assert code == 0
    assert calls == [("https://www.youtube.com/watch?v=test123", "u-1", True)]
    output = capsys.readouterr().out
    assert '"success": true' in output
    assert '"marker": "indexed"' in output


def test_ingest_item_returns_nonzero_for_failed_result(monkeypatch) -> None:
    class FakeIngestService:
        def ingest_single_url(self, url: str, *, user_id=None, force_refresh=False):
            return _Result(success=False)

    monkeypatch.setattr(ingest_item, "IngestService", FakeIngestService)
    assert ingest_item.main(["https://www.youtube.com/watch?v=test123"]) == 1


def test_ingest_item_returns_two_for_exception(monkeypatch, capsys) -> None:
    class FakeIngestService:
        def ingest_single_url(self, url: str, *, user_id=None, force_refresh=False):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(ingest_item, "IngestService", FakeIngestService)
    assert ingest_item.main(["https://www.youtube.com/watch?v=test123"]) == 2
    assert "provider unavailable" in capsys.readouterr().out


def _settings(tmp_path: Path) -> SimpleNamespace:
    data_dir = tmp_path / "memory-data"
    return SimpleNamespace(
        sqlite_path=str(data_dir / "memory.sqlite3"),
        chroma_persist_dir=str(data_dir / "chroma"),
        transcript_artifact_dir=str(data_dir / "transcripts"),
    )


def test_reset_local_data_dry_run_is_non_destructive(tmp_path) -> None:
    settings = _settings(tmp_path)
    sqlite_path = Path(settings.sqlite_path)
    sqlite_path.parent.mkdir(parents=True)
    sqlite_path.write_text("db", encoding="utf-8")
    Path(settings.chroma_persist_dir).mkdir()

    existing = reset_db.reset_local_data(settings, dry_run=True)

    assert sqlite_path in existing
    assert Path(settings.chroma_persist_dir) in existing
    assert sqlite_path.exists()
    assert Path(settings.chroma_persist_dir).exists()


def test_reset_local_data_removes_only_configured_targets(tmp_path) -> None:
    settings = _settings(tmp_path)
    sqlite_path = Path(settings.sqlite_path)
    sqlite_path.parent.mkdir(parents=True)
    sqlite_path.write_text("db", encoding="utf-8")
    wal = Path(f"{sqlite_path}-wal")
    wal.write_text("wal", encoding="utf-8")
    chroma = Path(settings.chroma_persist_dir)
    chroma.mkdir()
    (chroma / "index.bin").write_text("index", encoding="utf-8")
    transcripts = Path(settings.transcript_artifact_dir)
    transcripts.mkdir()
    (transcripts / "item.json").write_text("{}", encoding="utf-8")
    unrelated = tmp_path / "keep-me.txt"
    unrelated.write_text("keep", encoding="utf-8")

    removed = reset_db.reset_local_data(settings)

    assert set(removed) == {sqlite_path.resolve(), wal.resolve(), chroma.resolve(), transcripts.resolve()}
    assert not sqlite_path.exists()
    assert not wal.exists()
    assert not chroma.exists()
    assert not transcripts.exists()
    assert unrelated.exists()


def test_reset_rejects_dangerous_targets(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    settings.sqlite_path = str(Path.home())

    with pytest.raises(ValueError, match="unsafe path"):
        reset_db.reset_local_data(settings, dry_run=True)
