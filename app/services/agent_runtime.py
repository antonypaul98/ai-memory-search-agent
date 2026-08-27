"""Deterministic Phase 4 agent runtime with typed tools and durable audit state.

This is intentionally not an LLM planner. It provides the safe execution substrate
that later agents can orchestrate: tenant isolation, policy checks, approval gates,
tool audit records, and domain events.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import Settings, get_settings
from app.db.schema import get_connection
from app.db.video_registry import get_video_registry
from app.models.agent_runtime import (
    AgentPolicyTier,
    AgentRunRequest,
    AgentRunResponse,
    AgentRunStatus,
    AgentToolCall,
)
from app.services.event_bus import EventBus
from app.services.ingest_service import IngestService
from app.services.search_service import SearchService


_WRITE_TOOLS = frozenset({"ingest_url", "record_feedback"})
_ALLOWED_TOOLS = frozenset({"search_memory", "ingest_url", "record_feedback"})


class AgentRuntime:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._events = EventBus(self._settings)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        with get_connection(self._settings) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_runs (
                    run_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    task TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    arguments_json TEXT NOT NULL DEFAULT '{}',
                    policy_tier TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_runs_user_created
                    ON agent_runs(user_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS agent_tool_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    status TEXT NOT NULL,
                    arguments_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES agent_runs(run_id)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_tool_calls_run
                    ON agent_tool_calls(run_id, id);
                """
            )

    def run(self, *, user_id: str, request: AgentRunRequest) -> AgentRunResponse:
        user_id = (user_id or "").strip()
        if not user_id:
            raise ValueError("user_id is required")
        if request.tool not in _ALLOWED_TOOLS:
            raise ValueError(f"unknown agent tool: {request.tool}")

        run_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        status = AgentRunStatus.RUNNING
        message = ""

        if request.tool in _WRITE_TOOLS and (
            request.policy_tier not in {AgentPolicyTier.WRITE_MEMORY, AgentPolicyTier.EXTERNAL, AgentPolicyTier.ADMIN}
            or not request.approved
        ):
            status = AgentRunStatus.AWAITING_APPROVAL
            message = "Memory write requires write_memory policy and explicit approval."

        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT INTO agent_runs (
                    run_id, user_id, agent_id, task, tool, arguments_json,
                    policy_tier, status, message, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    user_id,
                    request.agent_id,
                    request.task,
                    request.tool,
                    json.dumps(request.arguments, sort_keys=True),
                    request.policy_tier.value,
                    status.value,
                    message,
                    now,
                    now,
                ),
            )

        self._events.emit(
            user_id=user_id,
            event_type="agent.run.started",
            aggregate_type="agent_run",
            aggregate_id=run_id,
            actor=f"agent:{request.agent_id}",
            payload={"tool": request.tool, "policy_tier": request.policy_tier.value},
        )

        if status == AgentRunStatus.AWAITING_APPROVAL:
            self._events.emit(
                user_id=user_id,
                event_type="agent.run.awaiting_approval",
                aggregate_type="agent_run",
                aggregate_id=run_id,
                actor=f"agent:{request.agent_id}",
                payload={"tool": request.tool},
            )
            return self.get_run(user_id=user_id, run_id=run_id)

        return self._execute(user_id=user_id, run_id=run_id)

    def approve(self, *, user_id: str, run_id: str) -> AgentRunResponse:
        row = self._get_run_row(user_id=user_id, run_id=run_id)
        if row["status"] != AgentRunStatus.AWAITING_APPROVAL.value:
            raise ValueError("run is not awaiting approval")
        if row["policy_tier"] not in {
            AgentPolicyTier.WRITE_MEMORY.value,
            AgentPolicyTier.EXTERNAL.value,
            AgentPolicyTier.ADMIN.value,
        }:
            raise PermissionError("run policy does not allow memory writes")
        with get_connection(self._settings) as conn:
            conn.execute(
                "UPDATE agent_runs SET status = ?, message = '', updated_at = ? WHERE run_id = ? AND user_id = ?",
                (AgentRunStatus.RUNNING.value, datetime.now(timezone.utc).isoformat(), run_id, user_id),
            )
        self._events.emit(
            user_id=user_id,
            event_type="agent.run.approved",
            aggregate_type="agent_run",
            aggregate_id=run_id,
            actor="user",
            payload={"tool": row["tool"]},
        )
        return self._execute(user_id=user_id, run_id=run_id)

    def get_run(self, *, user_id: str, run_id: str) -> AgentRunResponse:
        row = self._get_run_row(user_id=user_id, run_id=run_id)
        with get_connection(self._settings) as conn:
            calls = conn.execute(
                """
                SELECT tool, status, arguments_json, result_json, error
                FROM agent_tool_calls
                WHERE run_id = ? AND user_id = ?
                ORDER BY id ASC
                """,
                (run_id, user_id),
            ).fetchall()
        tool_calls = [
            AgentToolCall(
                tool=r["tool"],
                status=r["status"],
                arguments=json.loads(r["arguments_json"] or "{}"),
                result=json.loads(r["result_json"]) if r["result_json"] else None,
                error=r["error"],
            )
            for r in calls
        ]
        return AgentRunResponse(
            run_id=row["run_id"],
            agent_id=row["agent_id"],
            task=row["task"],
            status=AgentRunStatus(row["status"]),
            policy_tier=AgentPolicyTier(row["policy_tier"]),
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            tool_calls=tool_calls,
            message=row["message"] or "",
        )

    def _execute(self, *, user_id: str, run_id: str) -> AgentRunResponse:
        row = self._get_run_row(user_id=user_id, run_id=run_id)
        tool = row["tool"]
        args = json.loads(row["arguments_json"] or "{}")
        started = datetime.now(timezone.utc).isoformat()
        call_id: int
        with get_connection(self._settings) as conn:
            cur = conn.execute(
                """
                INSERT INTO agent_tool_calls (
                    run_id, user_id, tool, status, arguments_json, created_at
                ) VALUES (?, ?, ?, 'running', ?, ?)
                """,
                (run_id, user_id, tool, json.dumps(args, sort_keys=True), started),
            )
            call_id = int(cur.lastrowid)

        self._events.emit(
            user_id=user_id,
            event_type="agent.tool.started",
            aggregate_type="agent_run",
            aggregate_id=run_id,
            actor=f"agent:{row['agent_id']}",
            payload={"tool": tool},
        )

        try:
            result = self._invoke_tool(tool=tool, user_id=user_id, arguments=args)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            with get_connection(self._settings) as conn:
                conn.execute(
                    "UPDATE agent_tool_calls SET status = 'failed', error = ? WHERE id = ?",
                    (error[:1000], call_id),
                )
                conn.execute(
                    """
                    UPDATE agent_runs
                    SET status = ?, message = ?, updated_at = ?
                    WHERE run_id = ? AND user_id = ?
                    """,
                    (
                        AgentRunStatus.FAILED.value,
                        error[:1000],
                        datetime.now(timezone.utc).isoformat(),
                        run_id,
                        user_id,
                    ),
                )
            self._events.emit(
                user_id=user_id,
                event_type="agent.run.failed",
                aggregate_type="agent_run",
                aggregate_id=run_id,
                actor=f"agent:{row['agent_id']}",
                payload={"tool": tool, "error_type": type(exc).__name__},
            )
            return self.get_run(user_id=user_id, run_id=run_id)

        result_json = json.dumps(result, sort_keys=True, default=str)
        with get_connection(self._settings) as conn:
            conn.execute(
                "UPDATE agent_tool_calls SET status = 'completed', result_json = ? WHERE id = ?",
                (result_json, call_id),
            )
            conn.execute(
                """
                UPDATE agent_runs
                SET status = ?, result_json = ?, message = ?, updated_at = ?
                WHERE run_id = ? AND user_id = ?
                """,
                (
                    AgentRunStatus.COMPLETED.value,
                    result_json,
                    "Completed successfully.",
                    datetime.now(timezone.utc).isoformat(),
                    run_id,
                    user_id,
                ),
            )
        self._events.emit(
            user_id=user_id,
            event_type="agent.run.completed",
            aggregate_type="agent_run",
            aggregate_id=run_id,
            actor=f"agent:{row['agent_id']}",
            payload={"tool": tool},
        )
        return self.get_run(user_id=user_id, run_id=run_id)

    def _invoke_tool(self, *, tool: str, user_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool == "search_memory":
            query = str(arguments.get("query") or "").strip()
            if not query:
                raise ValueError("search_memory requires query")
            limit = int(arguments.get("limit") or 5)
            if limit < 1 or limit > 20:
                raise ValueError("search_memory limit must be between 1 and 20")
            response = SearchService(self._settings).search(query, limit=limit, user_id=user_id)
            return response.model_dump(mode="json")

        if tool == "ingest_url":
            url = str(arguments.get("url") or "").strip()
            if not url:
                raise ValueError("ingest_url requires url")
            force_refresh = bool(arguments.get("force_refresh", False))
            item = IngestService(self._settings).ingest_single_url(
                url,
                user_id=user_id,
                force_refresh=force_refresh,
            )
            return item.model_dump(mode="json")

        if tool == "record_feedback":
            video_id = str(arguments.get("video_id") or "").strip()
            if not video_id:
                raise ValueError("record_feedback requires video_id")
            helpful = arguments.get("helpful")
            if not isinstance(helpful, bool):
                raise ValueError("record_feedback helpful must be boolean")
            registry = get_video_registry(self._settings)
            if not registry.get_video(video_id, user_id=user_id):
                raise KeyError("video not found")
            stats = registry.record_feedback(video_id, helpful=helpful, user_id=user_id)
            return stats.model_dump(mode="json")

        raise ValueError(f"unknown agent tool: {tool}")

    def _get_run_row(self, *, user_id: str, run_id: str):
        if not user_id or not run_id:
            raise ValueError("user_id and run_id are required")
        with get_connection(self._settings) as conn:
            row = conn.execute(
                "SELECT * FROM agent_runs WHERE run_id = ? AND user_id = ?",
                (run_id, user_id),
            ).fetchone()
        if row is None:
            raise KeyError("agent run not found")
        return row
