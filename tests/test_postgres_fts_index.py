from __future__ import annotations

import pytest

from app.db.postgres_fts_index import PostgresFTSIndex


class _Result:
    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchall(self):
        return list(self._rows)


class _Connection:
    def __init__(self, rows=None):
        self.calls: list[tuple[str, tuple | None]] = []
        self.rows = rows or []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())
        packed = tuple(params) if params is not None else None
        self.calls.append((normalized, packed))
        if normalized.startswith("SELECT doc_id"):
            return _Result(self.rows)
        return _Result()


class _Factory:
    def __init__(self, rows=None):
        self.connections: list[_Connection] = []
        self.rows = rows or []

    def __call__(self):
        conn = _Connection(self.rows)
        self.connections.append(conn)
        return conn

    @property
    def calls(self):
        return [call for conn in self.connections for call in conn.calls]


def test_schema_uses_composite_tenant_identity_and_gin_index():
    factory = _Factory()
    PostgresFTSIndex(factory)

    sql = " ".join(statement for statement, _params in factory.calls)
    assert "PRIMARY KEY (user_id, doc_id)" in sql
    assert "USING GIN(search_document)" in sql
    assert "ON memory_fts_documents(user_id, video_id, doc_id)" in sql


def test_upsert_is_scoped_by_tenant_and_never_conflicts_globally():
    factory = _Factory()
    index = PostgresFTSIndex(factory)

    index.upsert(
        user_id="tenant-a",
        video_id="video-1",
        level="evidence",
        doc_id="doc-1",
        title="Title",
        body="Private saved context",
    )

    sql, params = factory.calls[-1]
    assert "ON CONFLICT (user_id, doc_id) DO UPDATE" in sql
    assert params == (
        "tenant-a",
        "video-1",
        "evidence",
        "doc-1",
        "Title",
        "Private saved context",
    )


def test_search_requires_tenant_filter_and_deterministic_tie_break():
    rows = [
        {
            "doc_id": "doc-b",
            "video_id": "video-1",
            "level": "evidence",
            "title": "B",
            "snippet": "[memory] result",
            "score": 0.8,
        },
        {
            "doc_id": "doc-c",
            "video_id": "video-2",
            "level": "section",
            "title": "C",
            "snippet": "another [memory] result",
            "score": 0.7,
        },
    ]
    factory = _Factory(rows)
    index = PostgresFTSIndex(factory)

    results = index.search(
        "memory result",
        user_id="tenant-a",
        video_ids=["video-1", "video-2"],
        limit=500,
    )

    sql, params = factory.calls[-1]
    assert "WHERE user_id = %s" in sql
    assert "video_id = ANY(%s)" in sql
    assert "ORDER BY score DESC, doc_id ASC" in sql
    assert params == ("memory result", "tenant-a", ["video-1", "video-2"], 100)
    assert [result["rank"] for result in results] == [1, 2]
    assert results[0]["matched_text"] == "[memory] result"
    assert results[0]["relevance_score"] == 1.0
    assert results[1]["relevance_score"] == 0.5


def test_delete_is_tenant_scoped():
    factory = _Factory()
    index = PostgresFTSIndex(factory)

    index.delete_video("video-1", user_id="tenant-b")

    sql, params = factory.calls[-1]
    assert "WHERE user_id = %s AND video_id = %s" in sql
    assert params == ("tenant-b", "video-1")


@pytest.mark.parametrize("operation", ["upsert", "search", "delete"])
def test_blank_tenant_fails_closed(operation):
    factory = _Factory()
    index = PostgresFTSIndex(factory)

    with pytest.raises(ValueError, match="user_id is required"):
        if operation == "upsert":
            index.upsert(
                user_id=" ", video_id="v", level="evidence", doc_id="d", title="", body="x"
            )
        elif operation == "search":
            index.search("x", user_id=" ")
        else:
            index.delete_video("v", user_id=" ")


def test_blank_query_returns_without_database_search():
    factory = _Factory()
    index = PostgresFTSIndex(factory)
    schema_call_count = len(factory.calls)

    assert index.search("   ", user_id="tenant-a") == []
    assert len(factory.calls) == schema_call_count
