"""Regression coverage for the tenant-scoped Postgres semantic cache primitive."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.postgres_semantic_cache_store import PostgresSemanticCacheStore


class FakeResult:
    def __init__(self, *, row=None, rows=None, rowcount: int = 0) -> None:
        self._row = row
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple | None]] = []
        self.next_result = FakeResult()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql: str, params=None):
        self.calls.append((" ".join(sql.split()), params))
        result = self.next_result
        self.next_result = FakeResult()
        return result


class Factory:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def __call__(self):
        return self.connection


def _store() -> tuple[PostgresSemanticCacheStore, FakeConnection]:
    factory = Factory()
    store = PostgresSemanticCacheStore(factory)
    factory.connection.calls.clear()
    return store, factory.connection


def test_schema_has_tenant_composite_identity_and_index() -> None:
    factory = Factory()
    PostgresSemanticCacheStore(factory)
    sql = " ".join(statement for statement, _ in factory.connection.calls)

    assert "PRIMARY KEY (user_id, cache_key)" in sql
    assert "idx_semantic_cache_tenant_active" in sql
    assert "ON semantic_cache(user_id, expires_at, query_type)" in sql


def test_exact_lookup_is_tenant_scoped() -> None:
    store, conn = _store()
    conn.next_result = FakeResult(row={"cache_key": "k", "answer_json": "{}"})
    now = datetime.now(timezone.utc)

    row = store.get_exact(
        user_id="tenant-a",
        cache_key="k",
        query_type="factual",
        memory_index_version="3",
        preference_version="2",
        now=now,
    )

    assert row == {"cache_key": "k", "answer_json": "{}"}
    sql, params = conn.calls[-1]
    assert "WHERE user_id = %s AND cache_key = %s" in sql
    assert params == ("tenant-a", "k", "factual", "3", "2", now)


def test_candidate_scan_is_tenant_scoped_and_deterministic() -> None:
    store, conn = _store()
    conn.next_result = FakeResult(rows=[])
    now = datetime.now(timezone.utc)

    assert store.active_candidates(
        user_id="tenant-b",
        query_type="comparison",
        memory_index_version="1",
        preference_version="1",
        now=now,
    ) == []

    sql, params = conn.calls[-1]
    assert "WHERE user_id = %s AND query_type = %s" in sql
    assert "ORDER BY cache_key ASC" in sql
    assert params == ("tenant-b", "comparison", "1", "1", now)


def test_invalidation_cannot_cross_tenants() -> None:
    store, conn = _store()
    conn.next_result = FakeResult(rowcount=2)

    assert store.invalidate(user_id="tenant-a", query_type="factual") == 2
    sql, params = conn.calls[-1]
    assert sql.endswith("WHERE user_id = %s AND query_type = %s")
    assert params == ("tenant-a", "factual")


def test_missing_tenant_fails_closed_before_sql() -> None:
    store, conn = _store()
    before = len(conn.calls)

    with pytest.raises(ValueError, match="explicit tenant identity"):
        store.invalidate(user_id="")

    assert len(conn.calls) == before


def test_bump_index_version_invalidates_cache_atomically() -> None:
    store, conn = _store()
    conn.next_result = FakeResult(row={"value": "7"})

    assert store.bump_index_version() == "7"
    assert "RETURNING value" in conn.calls[-2][0]
    assert conn.calls[-1][0] == "DELETE FROM semantic_cache"
