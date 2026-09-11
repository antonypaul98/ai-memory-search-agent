from __future__ import annotations

from app.db.postgres_home_physical_memory_store import PostgresHomePhysicalMemoryStore


class Result:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def fetchall(self):
        return self.rows


class Connection:
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
        return Result()


def test_history_is_tenant_scoped_newest_first_and_provenance_preserving():
    statements = []
    rows = [
        {
            "object_name": "keys",
            "location": "desk",
            "observed_at": "2026-09-10T22:10:00+00:00",
            "confidence": 0.94,
            "source_id": "camera-office",
            "evidence_id": "frame-11",
        },
        {
            "object_name": "keys",
            "location": "entry table",
            "observed_at": "2026-09-10T22:05:00+00:00",
            "confidence": 0.91,
            "source_id": "camera-entry",
            "evidence_id": "frame-9",
        },
    ]
    connections = iter([Connection(statements), Connection(statements, [Result(rows)])])
    store = PostgresHomePhysicalMemoryStore(lambda: next(connections))

    history = store.history(
        user_id="tenant-a",
        object_name="KEYS",
        min_confidence=0.8,
        limit=2,
    )

    assert [item.location for item in history] == ["desk", "entry table"]
    assert [item.evidence_id for item in history] == ["frame-11", "frame-9"]
    statement, params = statements[-1]
    assert "WHERE user_id = %s" in statement
    assert "ORDER BY observed_at DESC, evidence_id DESC" in statement
    assert "LIMIT %s" in statement
    assert params == ("tenant-a", "KEYS", 0.8, 2)
