"""Phase 4b agent runtime, tool policy, audit, and API tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.models.agent_runtime import AgentPolicyTier, AgentRunRequest, AgentRunStatus
from app.models.user import LOCAL_DEFAULT_USER_ID
from app.services.agent_runtime import AgentRuntime
from app.services.event_bus import EventBus


class TestAgentRuntime:
    def test_search_memory_executes_read_only_and_is_tenant_scoped(
        self, test_settings: Settings
    ) -> None:
        runtime = AgentRuntime(test_settings)
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {"query": "RAG", "results": []}
        with patch("app.services.agent_runtime.SearchService") as MockSearch:
            MockSearch.return_value.search.return_value = mock_response
            out = runtime.run(
                user_id="tenant-a",
                request=AgentRunRequest(
                    task="Find my RAG memories",
                    tool="search_memory",
                    arguments={"query": "RAG", "limit": 3},
                    policy_tier=AgentPolicyTier.READ_ONLY,
                ),
            )
        assert out.status == AgentRunStatus.COMPLETED
        assert out.result == {"query": "RAG", "results": []}
        assert len(out.tool_calls) == 1
        MockSearch.return_value.search.assert_called_once_with(
            "RAG", limit=3, user_id="tenant-a"
        )

    def test_ingest_requires_write_policy_and_explicit_approval(
        self, test_settings: Settings
    ) -> None:
        runtime = AgentRuntime(test_settings)
        out = runtime.run(
            user_id="tenant-a",
            request=AgentRunRequest(
                task="Save this video",
                tool="ingest_url",
                arguments={"url": "https://youtu.be/abc123"},
                policy_tier=AgentPolicyTier.READ_ONLY,
            ),
        )
        assert out.status == AgentRunStatus.AWAITING_APPROVAL
        assert out.tool_calls == []

        with patch("app.services.agent_runtime.IngestService") as MockIngest:
            item = MagicMock()
            item.model_dump.return_value = {"success": True, "video_id": "abc123"}
            MockIngest.return_value.ingest_single_url.return_value = item
            try:
                runtime.approve(user_id="tenant-a", run_id=out.run_id)
                assert False, "read-only run must not be approvable for writes"
            except PermissionError:
                pass
        MockIngest.assert_not_called()

    def test_write_memory_run_waits_then_executes_after_approval(
        self, test_settings: Settings
    ) -> None:
        runtime = AgentRuntime(test_settings)
        pending = runtime.run(
            user_id="tenant-a",
            request=AgentRunRequest(
                task="Save this video",
                tool="ingest_url",
                arguments={"url": "https://youtu.be/abc123"},
                policy_tier=AgentPolicyTier.WRITE_MEMORY,
            ),
        )
        assert pending.status == AgentRunStatus.AWAITING_APPROVAL

        with patch("app.services.agent_runtime.IngestService") as MockIngest:
            item = MagicMock()
            item.model_dump.return_value = {"success": True, "video_id": "abc123"}
            MockIngest.return_value.ingest_single_url.return_value = item
            done = runtime.approve(user_id="tenant-a", run_id=pending.run_id)
        assert done.status == AgentRunStatus.COMPLETED
        assert done.result["success"] is True
        MockIngest.return_value.ingest_single_url.assert_called_once_with(
            "https://youtu.be/abc123",
            user_id="tenant-a",
            force_refresh=False,
        )

    def test_record_feedback_requires_approval_and_is_tenant_scoped(
        self, test_settings: Settings
    ) -> None:
        runtime = AgentRuntime(test_settings)
        pending = runtime.run(
            user_id="tenant-a",
            request=AgentRunRequest(
                task="Mark this memory helpful",
                tool="record_feedback",
                arguments={"video_id": "vid-1", "helpful": True},
                policy_tier=AgentPolicyTier.WRITE_MEMORY,
            ),
        )
        assert pending.status == AgentRunStatus.AWAITING_APPROVAL

        with patch("app.services.agent_runtime.get_video_registry") as get_registry:
            registry = get_registry.return_value
            registry.get_video.return_value = {"video_id": "vid-1"}
            stats = MagicMock()
            stats.model_dump.return_value = {"video_id": "vid-1", "helpful_count": 1}
            registry.record_feedback.return_value = stats
            done = runtime.approve(user_id="tenant-a", run_id=pending.run_id)

        assert done.status == AgentRunStatus.COMPLETED
        registry.get_video.assert_called_once_with("vid-1", user_id="tenant-a")
        registry.record_feedback.assert_called_once_with(
            "vid-1", helpful=True, user_id="tenant-a"
        )

    def test_record_feedback_rejects_non_boolean_helpful(
        self, test_settings: Settings
    ) -> None:
        runtime = AgentRuntime(test_settings)
        with patch("app.services.agent_runtime.get_video_registry") as get_registry:
            out = runtime.run(
                user_id="tenant-a",
                request=AgentRunRequest(
                    task="Bad feedback",
                    tool="record_feedback",
                    arguments={"video_id": "vid-1", "helpful": "yes"},
                    policy_tier=AgentPolicyTier.WRITE_MEMORY,
                    approved=True,
                ),
            )
        assert out.status == AgentRunStatus.FAILED
        assert "helpful must be boolean" in out.message
        get_registry.assert_not_called()

    def test_unknown_tool_rejected_before_run_is_created(self, test_settings: Settings) -> None:
        runtime = AgentRuntime(test_settings)
        try:
            runtime.run(
                user_id="tenant-a",
                request=AgentRunRequest(
                    task="Do something unsafe",
                    tool="memory_write_raw",
                    arguments={},
                ),
            )
            assert False, "unknown/raw tool must be rejected"
        except ValueError as exc:
            assert "unknown agent tool" in str(exc)

    def test_run_lookup_is_tenant_isolated(self, test_settings: Settings) -> None:
        runtime = AgentRuntime(test_settings)
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {"query": "x", "results": []}
        with patch("app.services.agent_runtime.SearchService") as MockSearch:
            MockSearch.return_value.search.return_value = mock_response
            run = runtime.run(
                user_id="tenant-a",
                request=AgentRunRequest(
                    task="search",
                    tool="search_memory",
                    arguments={"query": "x"},
                ),
            )
        try:
            runtime.get_run(user_id="tenant-b", run_id=run.run_id)
            assert False, "cross-tenant run lookup must fail"
        except KeyError:
            pass

    def test_agent_events_are_persisted(self, test_settings: Settings) -> None:
        runtime = AgentRuntime(test_settings)
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {"query": "events", "results": []}
        with patch("app.services.agent_runtime.SearchService") as MockSearch:
            MockSearch.return_value.search.return_value = mock_response
            run = runtime.run(
                user_id="tenant-a",
                request=AgentRunRequest(
                    task="search",
                    tool="search_memory",
                    arguments={"query": "events"},
                ),
            )
        events, _ = EventBus(test_settings).list_events(user_id="tenant-a", limit=20)
        types = [e.event_type for e in events if e.aggregate_id == run.run_id]
        assert "agent.run.started" in types
        assert "agent.tool.started" in types
        assert "agent.run.completed" in types


class TestAgentRuntimeAPI:
    def test_run_and_get_search_agent(self, client: TestClient) -> None:
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {"query": "MCP", "results": []}
        with patch("app.services.agent_runtime.SearchService") as MockSearch:
            MockSearch.return_value.search.return_value = mock_response
            resp = client.post(
                "/api/v1/agents/run",
                json={
                    "agent_id": "memory_tools",
                    "task": "Find MCP memories",
                    "tool": "search_memory",
                    "arguments": {"query": "MCP"},
                    "policy_tier": "read_only",
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        fetched = client.get(f"/api/v1/agents/runs/{body['run_id']}")
        assert fetched.status_code == 200
        assert fetched.json()["run_id"] == body["run_id"]
        assert fetched.json()["tool_calls"][0]["tool"] == "search_memory"

    def test_write_agent_requires_approval(self, client: TestClient) -> None:
        pending = client.post(
            "/api/v1/agents/run",
            json={
                "agent_id": "memory_tools",
                "task": "Save video",
                "tool": "ingest_url",
                "arguments": {"url": "https://youtu.be/abc123"},
                "policy_tier": "write_memory",
            },
        )
        assert pending.status_code == 200
        assert pending.json()["status"] == "awaiting_approval"

        with patch("app.services.agent_runtime.IngestService") as MockIngest:
            item = MagicMock()
            item.model_dump.return_value = {"success": True, "video_id": "abc123"}
            MockIngest.return_value.ingest_single_url.return_value = item
            approved = client.post(
                f"/api/v1/agents/runs/{pending.json()['run_id']}/approve"
            )
        assert approved.status_code == 200
        assert approved.json()["status"] == "completed"

    def test_unknown_tool_is_400(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/agents/run",
            json={
                "task": "unsafe",
                "tool": "memory_write_raw",
                "arguments": {},
                "policy_tier": "admin",
                "approved": True,
            },
        )
        assert resp.status_code == 400

    def test_missing_run_is_404(self, client: TestClient) -> None:
        resp = client.get("/api/v1/agents/runs/does-not-exist")
        assert resp.status_code == 404

    def test_default_demo_user_is_preserved(self, client: TestClient) -> None:
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {"query": "demo", "results": []}
        with patch("app.services.agent_runtime.SearchService") as MockSearch:
            MockSearch.return_value.search.return_value = mock_response
            resp = client.post(
                "/api/v1/agents/run",
                json={
                    "task": "search demo",
                    "tool": "search_memory",
                    "arguments": {"query": "demo"},
                },
            )
        assert resp.status_code == 200
        MockSearch.return_value.search.assert_called_once_with(
            "demo", limit=5, user_id=LOCAL_DEFAULT_USER_ID
        )
