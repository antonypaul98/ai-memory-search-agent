from __future__ import annotations

import sqlite3

import pytest

from app.config import Settings
from app.db import fts_retrieval_parity as parity


def _source_db(path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE VIRTUAL TABLE memory_fts USING fts5(video_id, level, doc_id UNINDEXED, title, body)"
    )
    conn.executemany(
        "INSERT INTO memory_fts(video_id, level, doc_id, title, body) VALUES (?, ?, ?, ?, ?)",
        [
            ("v1", "capsule", "doc-a", "Alpha", "shared migration token"),
            ("v2", "section", "doc-b", "Beta", "shared migration token"),
        ],
    )
    conn.commit()
    conn.close()


class _FakePostgresFTS:
    results: list[dict] = []
    seen_user_ids: list[str] = []

    def __init__(self, connection_factory) -> None:
        del connection_factory

    def search(self, query: str, *, user_id: str, limit: int = 20, video_ids=None):
        del query, limit, video_ids
        self.seen_user_ids.append(user_id)
        return list(self.results)


def test_parity_passes_for_exact_ordered_identity_match(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    _source_db(source)
    settings = Settings(sqlite_path=str(source))
    _FakePostgresFTS.results = [{"doc_id": "doc-a"}, {"doc_id": "doc-b"}]
    _FakePostgresFTS.seen_user_ids = []
    monkeypatch.setattr(parity, "PostgresFTSIndex", _FakePostgresFTS)

    report = parity.validate_lexical_retrieval_parity(
        ["shared migration token"],
        user_id=" tenant-a ",
        settings=settings,
        connection_factory=lambda: None,
    )

    assert report.passed is True
    assert report.queries_checked == 1
    assert report.queries_matched == 1
    assert report.mismatches == ()
    assert _FakePostgresFTS.seen_user_ids == ["tenant-a"]


def test_parity_fails_closed_on_order_or_identity_mismatch(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    _source_db(source)
    settings = Settings(sqlite_path=str(source))
    _FakePostgresFTS.results = [{"doc_id": "doc-b"}, {"doc_id": "doc-a"}]
    monkeypatch.setattr(parity, "PostgresFTSIndex", _FakePostgresFTS)

    report = parity.validate_lexical_retrieval_parity(
        ["shared migration token"],
        user_id="tenant-a",
        settings=settings,
        connection_factory=lambda: None,
    )

    assert report.passed is False
    assert report.queries_matched == 0
    assert report.mismatches[0].query_index == 1
    assert report.mismatches[0].sqlite_doc_ids == ("doc-a", "doc-b")
    assert report.mismatches[0].postgres_doc_ids == ("doc-b", "doc-a")


def test_report_never_echoes_private_query_text(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    _source_db(source)
    settings = Settings(sqlite_path=str(source))
    _FakePostgresFTS.results = []
    monkeypatch.setattr(parity, "PostgresFTSIndex", _FakePostgresFTS)
    private_query = "shared migration token"

    report = parity.validate_lexical_retrieval_parity(
        [private_query],
        user_id="tenant-a",
        settings=settings,
        connection_factory=lambda: None,
    )

    assert private_query not in str(report.to_dict())


def test_parity_requires_explicit_tenant_and_nonempty_query_suite(tmp_path):
    source = tmp_path / "source.db"
    _source_db(source)
    settings = Settings(sqlite_path=str(source))

    with pytest.raises(ValueError, match="user_id is required"):
        parity.validate_lexical_retrieval_parity(
            ["token"], user_id=" ", settings=settings, connection_factory=lambda: None
        )

    with pytest.raises(ValueError, match="at least one non-empty"):
        parity.validate_lexical_retrieval_parity(
            [" ", ""], user_id="tenant-a", settings=settings, connection_factory=lambda: None
        )
