"""J01 Jarvis core runtime acceptance tests."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.models.jarvis import JarvisRequest
from app.services.jarvis_core_runtime import JarvisCoreRuntime


class TestJarvisCoreRuntime:
    def test_search_runs_end_to_end_through_existing_command_router(
        self, test_settings: Settings
    ) -> None:
        runtime = JarvisCoreRuntime(test_settings)
        with patch.object(runtime._commands, "execute") as execute:
            execute.return_value = {
                "ok": True,
                "status": "executed",
                "message": "Found 1 result(s).",
                "result": {"query": "RAG", "results": [{"memory_id": "m1"}]},
            }
            out = runtime.run(
                user_id="tenant-a",
                request=JarvisRequest(text="find RAG", limit=3),
            )
        assert out.plan.intent == "search"
        assert out.executed is True
        assert out.result["query"] == "RAG"
        execute.assert_called_once()
        assert execute.call_args.kwargs["user_id"] == "tenant-a"
        assert execute.call_args.kwargs["limit"] == 3

    def test_memory_question_routes_to_grounded_ask(
        self, test_settings: Settings
    ) -> None:
        runtime = JarvisCoreRuntime(test_settings)
        with patch.object(runtime._commands, "execute") as execute:
            execute.return_value = {
                "ok": True,
                "status": "executed",
                "message": "Answered from memory.",
                "result": {"answer": "summary", "citations": ["m1"]},
            }
            out = runtime.run(
                user_id="tenant-a",
                request=JarvisRequest(text="summarize what I saved about vector databases"),
            )
        assert out.plan.intent == "ask"
        assert out.executed is True
        assert out.result["citations"] == ["m1"]
        assert execute.call_args.kwargs["user_id"] == "tenant-a"

    def test_write_intent_is_gated_and_never_executed(
        self, test_settings: Settings
    ) -> None:
        runtime = JarvisCoreRuntime(test_settings)
        with patch.object(runtime._commands, "execute") as execute:
            out = runtime.run(
                user_id="tenant-a",
                request=JarvisRequest(
                    text="save",
                    context={"url": "https://example.com", "title": "Example"},
                ),
            )
        assert out.plan.intent == "save"
        assert out.executed is False
        assert out.status == "action_gated"
        execute.assert_not_called()

    def test_tenant_identity_is_required(self, test_settings: Settings) -> None:
        runtime = JarvisCoreRuntime(test_settings)
        try:
            runtime.run(user_id="", request=JarvisRequest(text="find RAG"))
            assert False, "empty tenant must fail closed"
        except ValueError as exc:
            assert "user_id is required" in str(exc)


class TestJarvisCoreRuntimeAPI:
    def test_authenticated_route_uses_current_tenant(self, client: TestClient) -> None:
        with patch("app.services.jarvis_core_runtime.CommandRouterService.execute") as execute:
            execute.return_value = {
                "ok": True,
                "status": "executed",
                "message": "Found 0 result(s).",
                "result": {"query": "MCP", "results": []},
            }
            response = client.post("/api/v1/jarvis/run", json={"text": "find MCP"})
        assert response.status_code == 200
        body = response.json()
        assert body["plan"]["intent"] == "search"
        assert body["executed"] is True

    def test_api_does_not_execute_write_intent(self, client: TestClient) -> None:
        with patch("app.services.jarvis_core_runtime.CommandRouterService.execute") as execute:
            response = client.post(
                "/api/v1/jarvis/run",
                json={
                    "text": "save",
                    "context": {"url": "https://example.com", "title": "Example"},
                },
            )
        assert response.status_code == 200
        assert response.json()["status"] == "action_gated"
        execute.assert_not_called()
