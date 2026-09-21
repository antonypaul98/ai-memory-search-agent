"""Postgres persistence for tenant-scoped deterministic agent runtime state."""
from __future__ import annotations

from typing import Any

from app.db.postgres_job_repository import ConnectionFactory


class PostgresAgentRuntimeStore:
    """Persist agent runs/tool calls while honoring the account-erasure fence."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory
        with connection_factory() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS account_erasure_fences (
                    user_id TEXT PRIMARY KEY, fenced_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS agent_runs (
                    run_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, agent_id TEXT NOT NULL,
                    task TEXT NOT NULL, tool TEXT NOT NULL, arguments_json TEXT NOT NULL DEFAULT '{}',
                    policy_tier TEXT NOT NULL, status TEXT NOT NULL, result_json TEXT,
                    message TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_user_created ON agent_runs(user_id, created_at DESC)")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS agent_tool_calls (
                    id BIGSERIAL PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL, tool TEXT NOT NULL, status TEXT NOT NULL,
                    arguments_json TEXT NOT NULL DEFAULT '{}', result_json TEXT, error TEXT,
                    created_at TEXT NOT NULL
                )"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_tool_calls_run ON agent_tool_calls(run_id, id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_tool_calls_tenant ON agent_tool_calls(user_id, run_id, id)")

    @staticmethod
    def _require_active(conn: Any, *, user_id: str) -> None:
        row = conn.execute(
            "SELECT 1 FROM account_erasure_fences WHERE user_id=%s", (user_id,)
        ).fetchone()
        if row is not None:
            raise PermissionError("account erasure is in progress or completed")

    def create_run(self, *, run_id: str, user_id: str, agent_id: str, task: str, tool: str,
                   arguments_json: str, policy_tier: str, status: str, message: str,
                   created_at: str) -> None:
        with self._connection_factory() as conn:
            self._require_active(conn, user_id=user_id)
            conn.execute(
                """INSERT INTO agent_runs (
                    run_id, user_id, agent_id, task, tool, arguments_json,
                    policy_tier, status, message, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (run_id, user_id, agent_id, task, tool, arguments_json,
                 policy_tier, status, message, created_at, created_at),
            )

    def get_run(self, *, user_id: str, run_id: str) -> dict[str, Any] | None:
        with self._connection_factory() as conn:
            row = conn.execute("SELECT * FROM agent_runs WHERE run_id=%s AND user_id=%s", (run_id, user_id)).fetchone()
        return dict(row) if row else None

    def list_tool_calls(self, *, user_id: str, run_id: str) -> list[dict[str, Any]]:
        with self._connection_factory() as conn:
            rows = conn.execute(
                """SELECT tool, status, arguments_json, result_json, error
                FROM agent_tool_calls WHERE run_id=%s AND user_id=%s ORDER BY id ASC""",
                (run_id, user_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_run_running(self, *, user_id: str, run_id: str, updated_at: str) -> None:
        with self._connection_factory() as conn:
            self._require_active(conn, user_id=user_id)
            conn.execute(
                "UPDATE agent_runs SET status='running', message='', updated_at=%s WHERE run_id=%s AND user_id=%s",
                (updated_at, run_id, user_id),
            )

    def create_tool_call(self, *, user_id: str, run_id: str, tool: str,
                         arguments_json: str, created_at: str) -> int:
        with self._connection_factory() as conn:
            self._require_active(conn, user_id=user_id)
            row = conn.execute(
                """INSERT INTO agent_tool_calls (
                    run_id, user_id, tool, status, arguments_json, created_at
                ) VALUES (%s, %s, %s, 'running', %s, %s) RETURNING id""",
                (run_id, user_id, tool, arguments_json, created_at),
            ).fetchone()
        return int(row["id"])

    def mark_failed(self, *, user_id: str, run_id: str, call_id: int,
                    error: str, updated_at: str) -> None:
        with self._connection_factory() as conn:
            conn.execute("UPDATE agent_tool_calls SET status='failed', error=%s WHERE id=%s AND run_id=%s AND user_id=%s", (error, call_id, run_id, user_id))
            conn.execute("UPDATE agent_runs SET status='failed', message=%s, updated_at=%s WHERE run_id=%s AND user_id=%s", (error, updated_at, run_id, user_id))

    def mark_completed(self, *, user_id: str, run_id: str, call_id: int,
                       result_json: str, message: str, updated_at: str) -> None:
        with self._connection_factory() as conn:
            conn.execute("UPDATE agent_tool_calls SET status='completed', result_json=%s WHERE id=%s AND run_id=%s AND user_id=%s", (result_json, call_id, run_id, user_id))
            conn.execute("UPDATE agent_runs SET status='completed', result_json=%s, message=%s, updated_at=%s WHERE run_id=%s AND user_id=%s", (result_json, message, updated_at, run_id, user_id))

    def delete_for_user(self, *, user_id: str) -> dict[str, int]:
        owner = user_id.strip()
        if not owner:
            raise ValueError("user_id is required")
        with self._connection_factory() as conn:
            tool_calls = conn.execute(
                """DELETE FROM agent_tool_calls child USING agent_runs parent
                   WHERE child.run_id = parent.run_id AND parent.user_id=%s RETURNING child.id""",
                (owner,),
            ).fetchall()
            runs = conn.execute("DELETE FROM agent_runs WHERE user_id=%s RETURNING run_id", (owner,)).fetchall()
        return {"agent_tool_calls": len(tool_calls), "agent_runs": len(runs)}
