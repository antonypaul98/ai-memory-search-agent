"""Tenant-isolation tests for Postgres model-usage privacy primitives."""
from __future__ import annotations

from contextlib import contextmanager

import pytest

from app.db.postgres_model_usage_privacy import (
    delete_user_model_usage,
    export_user_model_usage,
)


class _Result:
    def __init__(self, rows=None, rowcount: int = 0):
        self._rows = list(rows or [])
        self.rowcount = rowcount

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self):
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def execute(self, sql: str, params: tuple[str, ...]):
        normalized = " ".join(sql.split())
        self.calls.append((normalized, params))
        if normalized.startswith("SELECT"):
            return _Result(
                [
                    {
                        "id": 7,
                        "user_id": "tenant-a",
                        "route_id": "provider:model",
                        "provider_id": "provider",
                        "model_id": "model",
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                        "created_at": "2026-09-14T00:00:00+00:00",
                    }
                ]
            )
        return _Result(rowcount=2)


@contextmanager
def _factory_for(conn: _Conn):
    yield conn


def test_model_usage_export_is_exact_tenant_and_deterministic():
    conn = _Conn()

    rows = export_user_model_usage(lambda: _factory_for(conn), user_id="tenant-a")

    assert len(rows) == 1
    assert rows[0]["user_id"] == "tenant-a"
    sql, params = conn.calls[0]
    assert "WHERE user_id = %s" in sql
    assert "ORDER BY created_at ASC, id ASC" in sql
    assert params == ("tenant-a",)


def test_model_usage_delete_is_exact_tenant():
    conn = _Conn()

    count = delete_user_model_usage(lambda: _factory_for(conn), user_id="tenant-a")

    assert count == 2
    assert conn.calls == [
        ("DELETE FROM model_route_usage WHERE user_id = %s", ("tenant-a",))
    ]


@pytest.mark.parametrize("operation", [export_user_model_usage, delete_user_model_usage])
def test_model_usage_privacy_rejects_blank_owner_before_sql(operation):
    conn = _Conn()

    with pytest.raises(ValueError, match="user_id is required"):
        operation(lambda: _factory_for(conn), user_id="  ")

    assert conn.calls == []
