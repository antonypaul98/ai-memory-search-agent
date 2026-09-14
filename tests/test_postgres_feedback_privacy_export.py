from __future__ import annotations

from app.db.postgres_feedback_store import PostgresFeedbackStore


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Connection:
    def __init__(self):
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=()):
        normalized = " ".join(sql.split())
        self.calls.append((normalized, tuple(params)))
        if "FROM answer_interactions" in normalized:
            return _Cursor([{"interaction_id": "ans-a", "user_id": "tenant-a"}])
        if "FROM answer_feedback" in normalized:
            return _Cursor([{"id": 1, "user_id": "tenant-a", "interaction_id": "ans-a"}])
        if "FROM feedback_credit_ledger" in normalized:
            return _Cursor([{"id": 2, "user_id": "tenant-a", "credits": 5}])
        if "FROM output_preferences" in normalized:
            return _Cursor([{"user_id": "tenant-a", "task_type": "general"}])
        raise AssertionError(f"Unexpected SQL: {normalized}")


def test_feedback_privacy_export_scopes_every_relation_to_tenant():
    conn = _Connection()
    store = object.__new__(PostgresFeedbackStore)
    store._connection_factory = lambda: conn

    payload = store.export_user_data(user_id="tenant-a")

    assert payload == {
        "interactions": [{"interaction_id": "ans-a", "user_id": "tenant-a"}],
        "feedback": [{"id": 1, "user_id": "tenant-a", "interaction_id": "ans-a"}],
        "credit_ledger": [{"id": 2, "user_id": "tenant-a", "credits": 5}],
        "output_preferences": [{"user_id": "tenant-a", "task_type": "general"}],
    }
    assert len(conn.calls) == 4
    for sql, params in conn.calls:
        assert "WHERE user_id = %s" in sql
        assert params == ("tenant-a",)
