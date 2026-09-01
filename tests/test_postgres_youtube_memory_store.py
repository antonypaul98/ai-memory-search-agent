from __future__ import annotations

from app.db.postgres_youtube_memory_store import PostgresYouTubeMemoryStore
from app.models.youtube_memory import YouTubeMemory
from app.services.sources.base_source import ProcessingStatus, TranscriptAvailability, TranscriptKind


class FakeResult:
    def __init__(self, *, one=None, many=None):
        self._one = one
        self._many = many or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._many


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


def _memory(*, user_id="tenant-a", video_id="abc123xyz"):
    return YouTubeMemory(
        memory_id=f"mem-{user_id}",
        user_id=user_id,
        video_id=video_id,
        url=f"https://youtube.com/watch?v={video_id}",
        title="Useful video",
        saved_at="2026-09-01T00:00:00+00:00",
        updated_at="2026-09-01T00:00:00+00:00",
        transcript_availability=TranscriptAvailability.AVAILABLE,
        transcript_kind=TranscriptKind.MANUAL,
        processing_status=ProcessingStatus.COMPLETED,
        content_hash="hash-a",
        tags=["memory"],
        raw_metadata={"source": "youtube"},
    )


def test_schema_uses_tenant_scoped_video_and_content_hash_identity():
    statements = []
    store = PostgresYouTubeMemoryStore(lambda: FakeConnection(statements))

    sql = "\n".join(statement for statement, _ in statements)
    assert "UNIQUE(user_id, video_id)" in sql
    assert "idx_youtube_memories_tenant_hash" in sql
    assert "ON youtube_memories(user_id, content_hash)" in sql
    assert "idx_youtube_memories_tenant_saved" in sql
    assert store is not None


def test_upsert_conflict_target_is_tenant_and_video():
    statements = []
    store = PostgresYouTubeMemoryStore(lambda: FakeConnection(statements))
    statements.clear()

    memory = _memory()
    returned = store.upsert(memory)

    statement, params = statements[-1]
    assert "ON CONFLICT(user_id, video_id) DO UPDATE" in statement
    assert params[1:3] == ("tenant-a", "abc123xyz")
    assert returned == memory


def test_get_and_content_hash_lookup_require_exact_tenant():
    statements = []
    connections = iter(
        [
            FakeConnection(statements),
            FakeConnection(statements, [FakeResult(one=None)]),
            FakeConnection(statements, [FakeResult(one=None)]),
        ]
    )
    store = PostgresYouTubeMemoryStore(lambda: next(connections))

    assert store.get("abc123xyz", user_id="tenant-a") is None
    assert store.get_by_content_hash("hash-a", user_id="tenant-b") is None

    get_sql, get_params = statements[-2]
    hash_sql, hash_params = statements[-1]
    assert "WHERE user_id = %s AND video_id = %s" in get_sql
    assert get_params == ("tenant-a", "abc123xyz")
    assert "WHERE user_id = %s AND content_hash = %s" in hash_sql
    assert hash_params == ("tenant-b", "hash-a")


def test_list_for_user_never_scans_other_tenants():
    statements = []
    connections = iter(
        [
            FakeConnection(statements),
            FakeConnection(statements, [FakeResult(many=[])]),
        ]
    )
    store = PostgresYouTubeMemoryStore(lambda: next(connections))

    assert store.list_for_user("tenant-a", limit=17) == []

    statement, params = statements[-1]
    assert "WHERE user_id = %s ORDER BY saved_at DESC LIMIT %s" in statement
    assert params == ("tenant-a", 17)


def test_blank_content_hash_never_queries_target():
    statements = []
    store = PostgresYouTubeMemoryStore(lambda: FakeConnection(statements))
    schema_statement_count = len(statements)

    assert store.get_by_content_hash("", user_id="tenant-a") is None
    assert len(statements) == schema_statement_count


def test_operational_schema_makes_retry_metrics_and_pipeline_tenant_scoped():
    statements = []
    PostgresYouTubeMemoryStore(lambda: FakeConnection(statements))

    sql = "\n".join(statement for statement, _ in statements)
    assert "idx_youtube_pipeline_tenant_run" in sql
    assert "ON youtube_pipeline_runs(user_id, run_id, id)" in sql
    assert "UNIQUE(user_id, connector_id, external_id)" in sql
    assert "idx_youtube_retry_tenant_due" in sql
    assert "PRIMARY KEY (user_id, metric_key, connector_id)" in sql


def test_pipeline_stage_read_requires_exact_tenant():
    statements = []
    connections = iter(
        [
            FakeConnection(statements),
            FakeConnection(statements, [FakeResult(many=[])]),
        ]
    )
    store = PostgresYouTubeMemoryStore(lambda: next(connections))

    assert store.list_pipeline_stages("run-1", user_id="tenant-b") == []
    statement, params = statements[-1]
    assert "WHERE user_id = %s AND run_id = %s ORDER BY id" in statement
    assert params == ("tenant-b", "run-1")


def test_retry_claim_is_tenant_and_connector_scoped_and_deterministic():
    statements = []
    connections = iter(
        [
            FakeConnection(statements),
            FakeConnection(statements, [FakeResult(many=[])]),
        ]
    )
    store = PostgresYouTubeMemoryStore(lambda: next(connections))

    assert store.claim_due_retries(user_id="tenant-a", limit=7) == []
    statement, params = statements[-1]
    assert "WHERE user_id = %s AND connector_id = %s AND dead_lettered = FALSE" in statement
    assert "ORDER BY next_attempt_at ASC, id ASC LIMIT %s" in statement
    assert params[0] == "tenant-a"
    assert params[-1] == 7


def test_metric_read_and_write_identity_include_tenant():
    statements = []
    connections = iter(
        [
            FakeConnection(statements),
            FakeConnection(statements, [FakeResult(one=None)]),
        ]
    )
    store = PostgresYouTubeMemoryStore(lambda: next(connections))

    store.bump_metric("retry_count", 1, user_id="tenant-b")
    select_sql, select_params = statements[-2]
    insert_sql, insert_params = statements[-1]
    assert "WHERE user_id = %s AND metric_key = %s AND connector_id = %s" in select_sql
    assert select_params[0:2] == ("tenant-b", "retry_count")
    assert "INSERT INTO youtube_connector_metrics" in insert_sql
    assert insert_params[0:2] == ("tenant-b", "retry_count")


def test_diagnostics_counts_are_tenant_scoped():
    statements = []
    connections = iter(
        [
            FakeConnection(statements),
            FakeConnection(
                statements,
                [
                    FakeResult(one={"c": 2}),
                    FakeResult(one={"c": 1}),
                    FakeResult(one={"c": 0}),
                    FakeResult(many=[]),
                ],
            ),
        ]
    )
    store = PostgresYouTubeMemoryStore(lambda: next(connections))

    diagnostics = store.diagnostics(user_id="tenant-a")
    assert diagnostics.videos_saved == 2
    diagnostic_sql = "\n".join(statement for statement, _ in statements[-4:])
    assert "youtube_memories WHERE user_id = %s" in diagnostic_sql
    assert diagnostic_sql.count("user_id = %s") >= 4
