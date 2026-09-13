from __future__ import annotations

import os
import sqlite3
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.fts_retrieval_parity import validate_lexical_retrieval_parity
from app.db.postgres_fts_migration import migrate_lexical_to_postgres
from app.db.postgres_runtime import get_postgres_connection_factory


pytestmark = pytest.mark.skipif(
    not os.getenv("MEMORY_AGENT_TEST_POSTGRES_DSN"),
    reason="real Postgres DSN required",
)


def _build_legacy_fts(path, *, prefix: str) -> tuple[str, str]:
    doc_a = f"{prefix}-a"
    doc_b = f"{prefix}-b"
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE memory_fts USING fts5(video_id, level, doc_id UNINDEXED, title, body)"
        )
        conn.executemany(
            "INSERT INTO memory_fts(video_id, level, doc_id, title, body) VALUES (?, ?, ?, ?, ?)",
            [
                (f"video-{prefix}-a", "capsule", doc_a, "Alpha", "shared parity token alphaonly"),
                (f"video-{prefix}-b", "capsule", doc_b, "Beta", "shared parity token betaonly"),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return doc_a, doc_b


def test_migrated_lexical_state_matches_sqlite_on_real_postgres(tmp_path):
    source = tmp_path / "legacy-fts.db"
    suffix = uuid4().hex
    tenant = f"fts-parity-{suffix}"
    other_tenant = tenant + "-other"
    doc_a, doc_b = _build_legacy_fts(source, prefix=suffix)

    settings = Settings(
        _env_file=None,
        sqlite_path=str(source),
        postgres_dsn_env="MEMORY_AGENT_TEST_POSTGRES_DSN",
    )
    factory = get_postgres_connection_factory(settings)

    try:
        report = migrate_lexical_to_postgres(
            settings,
            user_id=tenant,
            connection_factory=factory,
        )
        assert report.documents_seen == 2
        assert report.documents_inserted == 2
        assert report.documents_skipped_existing == 0

        parity = validate_lexical_retrieval_parity(
            ["alphaonly", "betaonly", "shared parity token", "missingterm"],
            user_id=tenant,
            settings=settings,
            connection_factory=factory,
            limit=20,
        )
        assert parity.passed is True
        assert parity.queries_checked == 4
        assert parity.queries_matched == 4
        assert parity.mismatches == ()

        # The migrated rows belong only to the explicit tenant. A second tenant
        # must not inherit source ownership merely because it uses the same query.
        with factory() as conn:
            visible_to_other = conn.execute(
                "SELECT doc_id FROM memory_fts_documents WHERE user_id = %s AND doc_id = ANY(%s)",
                (other_tenant, [doc_a, doc_b]),
            ).fetchall()
        assert visible_to_other == []

        # Re-running the migration is idempotent and cannot replace target state.
        retry = migrate_lexical_to_postgres(
            settings,
            user_id=tenant,
            connection_factory=factory,
        )
        assert retry.documents_seen == 2
        assert retry.documents_inserted == 0
        assert retry.documents_skipped_existing == 2
    finally:
        with factory() as conn:
            conn.execute(
                "DELETE FROM memory_fts_documents WHERE user_id IN (%s, %s) AND doc_id = ANY(%s)",
                (tenant, other_tenant, [doc_a, doc_b]),
            )
