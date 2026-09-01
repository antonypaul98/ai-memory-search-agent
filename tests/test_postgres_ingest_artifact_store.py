from __future__ import annotations

import pytest

from app.db.postgres_ingest_artifact_store import PostgresIngestArtifactStore


class FakeResult:
    def __init__(self, *, one=None):
        self._one = one

    def fetchone(self):
        return self._one


class FakeConnection:
    def __init__(self, statements, results=None):
        self.statements = statements
        self.results = list(results or [])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement, params=None):
        self.statements.append((" ".join(str(statement).split()), params))
        if self.results:
            return self.results.pop(0)
        return FakeResult()


def test_schema_keys_ingest_artifacts_by_tenant_and_video():
    statements = []
    PostgresIngestArtifactStore(lambda: FakeConnection(statements))

    sql = "\n".join(statement for statement, _ in statements)
    assert "PRIMARY KEY (user_id, video_id)" in sql
    assert "idx_ingest_artifacts_tenant_hash" in sql
    assert "ON ingest_artifacts(user_id, transcript_hash)" in sql


def test_transcript_unchanged_requires_exact_tenant_and_video():
    statements = []
    connections = iter(
        [
            FakeConnection(statements),
            FakeConnection(statements, [FakeResult(one={"transcript_hash": "hash-a"})]),
        ]
    )
    store = PostgresIngestArtifactStore(lambda: next(connections))

    assert store.transcript_unchanged(
        user_id="tenant-a", video_id="video-1", transcript_hash="hash-a"
    )
    statement, params = statements[-1]
    assert "WHERE user_id = %s AND video_id = %s" in statement
    assert params == ("tenant-a", "video-1")


def test_transcript_hash_upsert_does_not_clear_existing_capsule():
    statements = []
    connections = iter([FakeConnection(statements), FakeConnection(statements)])
    store = PostgresIngestArtifactStore(lambda: next(connections))

    store.store_transcript_hash(user_id="tenant-a", video_id="video-1", transcript_hash="hash-b")
    statement, params = statements[-1]
    assert "ON CONFLICT(user_id, video_id) DO UPDATE SET transcript_hash = EXCLUDED.transcript_hash" in statement
    assert "capsule_json = EXCLUDED.capsule_json" not in statement
    assert params[:3] == ("tenant-a", "video-1", "hash-b")


def test_capsule_upsert_does_not_clear_existing_transcript_hash():
    statements = []
    connections = iter([FakeConnection(statements), FakeConnection(statements)])
    store = PostgresIngestArtifactStore(lambda: next(connections))

    store.store_capsule_json(user_id="tenant-b", video_id="video-2", capsule_json='{"title":"x"}')
    statement, params = statements[-1]
    assert "ON CONFLICT(user_id, video_id) DO UPDATE SET capsule_json = EXCLUDED.capsule_json" in statement
    assert "transcript_hash = EXCLUDED.transcript_hash" not in statement
    assert params[:3] == ("tenant-b", "video-2", '{"title":"x"}')


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        ("transcript_unchanged", {"user_id": "", "video_id": "video-1", "transcript_hash": "h"}),
        ("store_transcript_hash", {"user_id": "tenant-a", "video_id": "", "transcript_hash": "h"}),
        ("store_capsule_json", {"user_id": "tenant-a", "video_id": "video-1", "capsule_json": ""}),
    ],
)
def test_blank_identity_or_payload_fails_closed(method, kwargs):
    statements = []
    store = PostgresIngestArtifactStore(lambda: FakeConnection(statements))
    schema_statement_count = len(statements)

    with pytest.raises(ValueError):
        getattr(store, method)(**kwargs)
    assert len(statements) == schema_statement_count
