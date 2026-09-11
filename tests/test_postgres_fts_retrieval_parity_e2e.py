from __future__ import annotations

import os
import sqlite3
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.fts_retrieval_parity import validate_lexical_retrieval_parity
from app.db.postgres_fts_index import PostgresFTSIndex
from app.db.postgres_runtime import get_postgres_connection_factory

TEST_DSN_ENV = "MEMORY_AGENT_TEST_POSTGRES_DSN"
pytestmark = pytest.mark.skipif(not os.getenv(TEST_DSN_ENV), reason="test Postgres DSN not configured")


def _source_db(path) -> None:
    with sqlite3.connect(path) as conn:
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


def test_real_postgres_lexical_parity_passes_and_mismatch_keeps_gate_closed(tmp_path):
    tenant = "fts-parity-" + uuid4().hex
    other = tenant + "-other"
    source = tmp_path / "source.db"
    _source_db(source)

    settings = Settings(sqlite_path=str(source), postgres_dsn_env=TEST_DSN_ENV)
    factory = get_postgres_connection_factory(settings)
    postgres = PostgresFTSIndex(factory)

    try:
        for doc_id, video_id, level, title in (
            ("doc-a", "v1", "capsule", "Alpha"),
            ("doc-b", "v2", "section", "Beta"),
        ):
            postgres.upsert(
                user_id=tenant,
                video_id=video_id,
                level=level,
                doc_id=doc_id,
                title=title,
                body="shared migration token",
            )

        # Same document identity in another tenant must never affect the target tenant.
        postgres.upsert(
            user_id=other,
            video_id="private-v",
            level="capsule",
            doc_id="doc-private",
            title="Private",
            body="shared migration token",
        )

        passed = validate_lexical_retrieval_parity(
            ["shared migration token"],
            user_id=tenant,
            settings=settings,
            connection_factory=factory,
        )
        assert passed.passed is True
        assert passed.queries_checked == 1
        assert passed.queries_matched == 1
        assert passed.mismatches == ()

        postgres.delete_video("v2", user_id=tenant)

        failed = validate_lexical_retrieval_parity(
            ["shared migration token"],
            user_id=tenant,
            settings=settings,
            connection_factory=factory,
        )
        assert failed.passed is False
        assert failed.queries_matched == 0
        assert failed.mismatches[0].query_index == 1
        assert failed.mismatches[0].sqlite_doc_ids == ("doc-a", "doc-b")
        assert failed.mismatches[0].postgres_doc_ids == ("doc-a",)

        report = failed.to_dict()
        assert report["passed"] is False
        assert report["mismatch_count"] == 1
        assert "shared migration token" not in str(report)
    finally:
        with factory() as conn:
            conn.execute(
                "DELETE FROM memory_fts_documents WHERE user_id IN (%s, %s)",
                (tenant, other),
            )
