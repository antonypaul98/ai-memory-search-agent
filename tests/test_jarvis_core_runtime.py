"""J01 Jarvis core runtime acceptance tests."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.models.jarvis import JarvisRequest
from app.services.jarvis_core_runtime import JarvisCoreRuntime
from app.services.command_router import reset_confirm_token_state


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


    def test_bulk_action_requires_explicit_confirmation(self, test_settings: Settings) -> None:
        reset_confirm_token_state()
        runtime = JarvisCoreRuntime(test_settings)
        preview = runtime.run(
            user_id="tenant-a",
            request=JarvisRequest(text="import bookmarks"),
        )
        assert preview.executed is False
        assert preview.status == "confirm_required"
        assert preview.plan.requires_confirm is True
        assert preview.plan.bulk is True
        assert preview.plan.confirm_token

    def test_bulk_confirmation_is_tenant_bound_and_single_use(self, test_settings: Settings) -> None:
        reset_confirm_token_state()
        runtime = JarvisCoreRuntime(test_settings)
        preview = runtime.run(
            user_id="tenant-a",
            request=JarvisRequest(text="import bookmarks"),
        )
        token = preview.plan.confirm_token
        assert token

        wrong_tenant = runtime.run(
            user_id="tenant-b",
            request=JarvisRequest(text="import bookmarks", confirm_token=token),
        )
        assert wrong_tenant.executed is False
        assert wrong_tenant.status == "confirm_required"

        confirmed = runtime.run(
            user_id="tenant-a",
            request=JarvisRequest(text="import bookmarks", confirm_token=token),
        )
        assert confirmed.executed is True
        assert confirmed.status == "handoff"
        assert confirmed.result["confirm_consumed"] is True

        replay = runtime.run(
            user_id="tenant-a",
            request=JarvisRequest(text="import bookmarks", confirm_token=token),
        )
        assert replay.executed is False
        assert replay.status == "confirm_required"

    def test_tampered_bulk_confirmation_fails_closed(self, test_settings: Settings) -> None:
        reset_confirm_token_state()
        runtime = JarvisCoreRuntime(test_settings)
        preview = runtime.run(
            user_id="tenant-a",
            request=JarvisRequest(text="import playlist"),
        )
        token = preview.plan.confirm_token
        assert token
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")

        out = runtime.run(
            user_id="tenant-a",
            request=JarvisRequest(text="import playlist", confirm_token=tampered),
        )
        assert out.executed is False
        assert out.status == "confirm_required"

    def test_tenant_identity_is_required(self, test_settings: Settings) -> None:
        runtime = JarvisCoreRuntime(test_settings)
        try:
            runtime.run(user_id="", request=JarvisRequest(text="find RAG"))
            assert False, "empty tenant must fail closed"
        except ValueError as exc:
            assert "user_id is required" in str(exc)


    def test_search_projects_bounded_provenance_context(self, test_settings: Settings) -> None:
        runtime = JarvisCoreRuntime(test_settings)
        with patch.object(runtime._commands, "execute") as execute:
            execute.return_value = {
                "ok": True,
                "status": "executed",
                "message": "Found results.",
                "result": {
                    "results": [
                        {
                            "memory_id": "m1",
                            "title": "One",
                            "matched_text": "alpha",
                            "citation_ref": "c1",
                            "source_type": "web",
                            "relevance_score": 0.9,
                        },
                        {
                            "memory_id": "m2",
                            "title": "Two",
                            "matched_text": "beta",
                            "citation_ref": "c2",
                            "source_type": "youtube",
                            "relevance_score": 0.8,
                        },
                    ]
                },
            }
            out = runtime.run(
                user_id="tenant-a",
                request=JarvisRequest(text="find vector databases", limit=1),
            )

        assert out.executed is True
        assert len(out.memory_context) == 1
        assert out.memory_context[0] == {
            "memory_id": "m1",
            "title": "One",
            "matched_text": "alpha",
            "citation_ref": "c1",
            "source_type": "web",
            "relevance_score": 0.9,
        }
        assert execute.call_args.kwargs["user_id"] == "tenant-a"

    def test_non_memory_action_never_projects_personal_context(self, test_settings: Settings) -> None:
        reset_confirm_token_state()
        runtime = JarvisCoreRuntime(test_settings)
        preview = runtime.run(
            user_id="tenant-a",
            request=JarvisRequest(text="import bookmarks"),
        )
        assert preview.executed is False
        assert preview.memory_context == []

    def test_ask_projects_only_returned_authenticated_memory_evidence(self, test_settings: Settings) -> None:
        runtime = JarvisCoreRuntime(test_settings)
        with patch.object(runtime._commands, "execute") as execute:
            execute.return_value = {
                "ok": True,
                "status": "executed",
                "message": "Answered from memory.",
                "result": {
                    "results": [
                        {
                            "memory_id": "m9",
                            "title": "Tenant result",
                            "matched_text": "grounded",
                            "citation_ref": "mem://m9",
                            "source_type": "memory",
                            "relevance_score": 1.0,
                        }
                    ],
                    "answer": "grounded answer",
                },
            }
            out = runtime.run(
                user_id="tenant-a",
                request=JarvisRequest(text="what did I save about MCP?", limit=3),
            )

        assert out.memory_context == [
            {
                "memory_id": "m9",
                "title": "Tenant result",
                "matched_text": "grounded",
                "citation_ref": "mem://m9",
                "source_type": "memory",
                "relevance_score": 1.0,
            }
        ]
        assert execute.call_args.kwargs["user_id"] == "tenant-a"


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


def test_context_projects_real_chat_response_schema():
    from app.models.chat import ChatResponse, ChatSource
    from app.services.jarvis_core_runtime import _memory_context
    response = ChatResponse(answer='Grounded answer', grounded=True, sources=[
        ChatSource(video_id='m1', title='Evidence', url='https://example.com/video',
                   matched_text='Saved text', relevance_score=0.9,
                   timestamp_url='https://example.com/video?t=12')
    ])
    context = _memory_context(response.model_dump(), limit=1)
    assert len(context) == 1
    assert context[0]['memory_id'] == 'm1'
    assert context[0]['citation_ref'] == 'https://example.com/video?t=12'
    assert context[0]['matched_text'] == 'Saved text'


def test_failed_command_does_not_project_context(test_settings):
    runtime = JarvisCoreRuntime(test_settings)
    with patch.object(runtime._commands, 'execute', return_value={
        'ok': False, 'status': 'error', 'result': {'results': [{'memory_id': 'm1'}]}
    }):
        out = runtime.run(user_id='tenant-a', request=JarvisRequest(text='find saved notes'))
    assert out.memory_context == []


def test_voice_route_reuses_authenticated_core_runtime(client: TestClient) -> None:
    with patch("app.services.jarvis_core_runtime.CommandRouterService.execute") as execute:
        execute.return_value = {
            "ok": True, "status": "executed", "message": "Found 0 result(s).",
            "result": {"query": "MCP", "results": []},
        }
        response = client.post("/api/v1/jarvis/voice", json={"transcript": "  find MCP  "})
    assert response.status_code == 200
    assert response.json()["plan"]["intent"] == "search"
    assert execute.call_args.kwargs["user_id"]


def test_voice_route_preserves_write_gate(client: TestClient) -> None:
    with patch("app.services.jarvis_core_runtime.CommandRouterService.execute") as execute:
        response = client.post("/api/v1/jarvis/voice", json={"transcript": "save"})
    assert response.status_code == 200
    assert response.json()["status"] == "action_gated"
    execute.assert_not_called()


def test_voice_route_rejects_empty_and_oversized_transcripts(client: TestClient) -> None:
    assert client.post("/api/v1/jarvis/voice", json={"transcript": "   "}).status_code == 422
    assert client.post("/api/v1/jarvis/voice", json={"transcript": "x" * 2001}).status_code == 422
