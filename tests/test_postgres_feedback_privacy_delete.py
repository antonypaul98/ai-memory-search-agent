"""Tenant-isolation tests for Postgres feedback privacy deletion."""
from __future__ import annotations

from contextlib import contextmanager

import pytest

from app.db.postgres_feedback_privacy import delete_user_feedback_data


class _Result:
    def __init__(self, rowcount: int):
        self.rowcount = rowcount


class _Conn:
    def __init__(self):
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def execute(self, sql: str, params: tuple[str, ...]):
        self.calls.append((" ".join(sql.split()), params))
        return _Result(1)


@contextmanager
def _factory_for(conn: _Conn):
    yield conn


def test_feedback_privacy_delete_scopes_every_relation_to_exact_tenant():
    conn = _Conn()

    counts = delete_user_feedback_data(
        lambda: _factory_for(conn),
        user_id="tenant-a",
    )

    assert counts == {
        "feedback": 1,
        "credit_ledger": 1,
        "output_preferences": 1,
        "interactions": 1,
    }
    assert [params for _, params in conn.calls] == [("tenant-a",)] * 4
    assert [sql for sql, _ in conn.calls] == [
        "DELETE FROM answer_feedback WHERE user_id = %s",
        "DELETE FROM feedback_credit_ledger WHERE user_id = %s",
        "DELETE FROM output_preferences WHERE user_id = %s",
        "DELETE FROM answer_interactions WHERE user_id = %s",
    ]


def test_feedback_privacy_delete_rejects_blank_owner_before_sql():
    conn = _Conn()

    with pytest.raises(ValueError, match="user_id is required"):
        delete_user_feedback_data(lambda: _factory_for(conn), user_id="   ")

    assert conn.calls == []
