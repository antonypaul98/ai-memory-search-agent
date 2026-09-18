"""P-03 privacy regressions for Postgres agent runtime state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.db.postgres_agent_runtime_store import PostgresAgentRuntimeStore


@dataclass
class _Result:
    rows: list[dict[str, Any]] = field(default_factory=list)

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...] | None]] = []

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Result:
        normalized = " ".join(sql.split())
        self.calls.append((normalized, params))
        if normalized.startswith("DELETE FROM agent_tool_calls"):
            return _Result([{"id": 1}, {"id": 2}])
        if normalized.startswith("DELETE FROM agent_runs"):
            return _Result([{"run_id": "run-a"}])
        return _Result()


def test_delete_for_user_uses_exact_tenant_predicate_on_children_and_parents() -> None:
    conn = _Connection()
    store = PostgresAgentRuntimeStore(lambda: conn)

    result = store.delete_for_user(user_id=" tenant-a ")

    assert result == {"agent_tool_calls": 2, "agent_runs": 1}
    deletes = [(sql, params) for sql, params in conn.calls if sql.startswith("DELETE FROM")]
    assert deletes == [
        ("DELETE FROM agent_tool_calls WHERE user_id=%s RETURNING id", ("tenant-a",)),
        ("DELETE FROM agent_runs WHERE user_id=%s RETURNING run_id", ("tenant-a",)),
    ]


def test_delete_for_user_rejects_blank_owner_before_opening_connection() -> None:
    calls = 0

    def factory() -> _Connection:
        nonlocal calls
        calls += 1
        return _Connection()

    store = PostgresAgentRuntimeStore(factory)
    constructor_calls = calls

    with pytest.raises(ValueError, match="user_id is required"):
        store.delete_for_user(user_id="   ")

    assert calls == constructor_calls
