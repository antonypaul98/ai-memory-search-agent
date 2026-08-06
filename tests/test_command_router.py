"""V1-7 agent command classifier, confirm gate, and API behavioral tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.models.user import LOCAL_DEFAULT_USER_ID
from app.services.command_router import (
    CommandIntent,
    CommandRouterService,
    classify_command,
    consume_confirm_token,
    mint_confirm_token,
    reset_confirm_token_state,
    verify_confirm_token,
)


class TestClassifyCommand:
    def test_search_prefix(self) -> None:
        c = classify_command("search MCP servers")
        assert c["intent"] == CommandIntent.SEARCH
        assert c["query"] == "MCP servers"
        assert c["requires_confirm"] is False

    def test_bare_keywords_default_search(self) -> None:
        c = classify_command("local LLM deployment")
        assert c["intent"] == CommandIntent.SEARCH
        assert "local LLM" in c["query"]

    def test_ask_patterns(self) -> None:
        c = classify_command("ask what did I learn about RAG")
        assert c["intent"] == CommandIntent.ASK
        c2 = classify_command("What have I saved about Docker?")
        assert c2["intent"] == CommandIntent.ASK

    def test_save_with_context(self) -> None:
        c = classify_command(
            "save",
            context={"url": "https://youtu.be/abc", "title": "Demo"},
        )
        assert c["intent"] == CommandIntent.SAVE
        assert c["bulk"] is False
        assert c["requires_confirm"] is False

    def test_import_bookmarks_is_bulk(self) -> None:
        c = classify_command("import bookmarks")
        assert c["intent"] == CommandIntent.IMPORT_BOOKMARKS
        assert c["bulk"] is True
        assert c["requires_confirm"] is True

    def test_import_playlist_is_bulk(self) -> None:
        c = classify_command("import playlist")
        assert c["intent"] == CommandIntent.IMPORT_PLAYLIST
        assert c["requires_confirm"] is True

    def test_help(self) -> None:
        c = classify_command("help")
        assert c["intent"] == CommandIntent.HELP

    def test_empty_unknown(self) -> None:
        c = classify_command("   ")
        assert c["intent"] == CommandIntent.UNKNOWN


class TestConfirmToken:
    def test_roundtrip(self, test_settings: Settings) -> None:
        token = mint_confirm_token(
            user_id=LOCAL_DEFAULT_USER_ID,
            intent=CommandIntent.IMPORT_BOOKMARKS,
            query="import bookmarks",
            settings=test_settings,
            now=1_700_000_000,
        )
        assert verify_confirm_token(
            token,
            user_id=LOCAL_DEFAULT_USER_ID,
            intent=CommandIntent.IMPORT_BOOKMARKS,
            query="import bookmarks",
            settings=test_settings,
            now=1_700_000_000 + 10,
        )

    def test_rejects_wrong_user(self, test_settings: Settings) -> None:
        token = mint_confirm_token(
            user_id="user-a",
            intent=CommandIntent.IMPORT_BOOKMARKS,
            query="import bookmarks",
            settings=test_settings,
            now=1_700_000_000,
        )
        assert not verify_confirm_token(
            token,
            user_id="user-b",
            intent=CommandIntent.IMPORT_BOOKMARKS,
            query="import bookmarks",
            settings=test_settings,
            now=1_700_000_000,
        )

    def test_rejects_expired(self, test_settings: Settings) -> None:
        token = mint_confirm_token(
            user_id=LOCAL_DEFAULT_USER_ID,
            intent=CommandIntent.IMPORT_PLAYLIST,
            query="import playlist",
            settings=test_settings,
            now=1_700_000_000,
            ttl_sec=60,
        )
        assert not verify_confirm_token(
            token,
            user_id=LOCAL_DEFAULT_USER_ID,
            intent=CommandIntent.IMPORT_PLAYLIST,
            query="import playlist",
            settings=test_settings,
            now=1_700_000_000 + 120,
        )

    def test_rejects_tampered_signature(self, test_settings: Settings) -> None:
        token = mint_confirm_token(
            user_id=LOCAL_DEFAULT_USER_ID,
            intent=CommandIntent.IMPORT_BOOKMARKS,
            query="import bookmarks",
            settings=test_settings,
            now=1_700_000_000,
        )
        # Flip last char of token payload
        tampered = token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1]
        assert not verify_confirm_token(
            tampered,
            user_id=LOCAL_DEFAULT_USER_ID,
            intent=CommandIntent.IMPORT_BOOKMARKS,
            query="import bookmarks",
            settings=test_settings,
            now=1_700_000_000,
        )

    def test_rejects_query_mismatch(self, test_settings: Settings) -> None:
        token = mint_confirm_token(
            user_id=LOCAL_DEFAULT_USER_ID,
            intent=CommandIntent.IMPORT_BOOKMARKS,
            query="import bookmarks",
            settings=test_settings,
            now=1_700_000_000,
        )
        assert not verify_confirm_token(
            token,
            user_id=LOCAL_DEFAULT_USER_ID,
            intent=CommandIntent.IMPORT_BOOKMARKS,
            query="import bookmarks now",
            settings=test_settings,
            now=1_700_000_000,
        )

    def test_accepts_missing_base64_padding(self, test_settings: Settings) -> None:
        token = mint_confirm_token(
            user_id=LOCAL_DEFAULT_USER_ID,
            intent=CommandIntent.IMPORT_BOOKMARKS,
            query="import bookmarks",
            settings=test_settings,
            now=1_700_000_000,
        )
        stripped = token.rstrip("=")
        assert verify_confirm_token(
            stripped,
            user_id=LOCAL_DEFAULT_USER_ID,
            intent=CommandIntent.IMPORT_BOOKMARKS,
            query="import bookmarks",
            settings=test_settings,
            now=1_700_000_000,
        )

    def test_consume_is_single_use(self, test_settings: Settings) -> None:
        reset_confirm_token_state()
        token = mint_confirm_token(
            user_id=LOCAL_DEFAULT_USER_ID,
            intent=CommandIntent.IMPORT_BOOKMARKS,
            query="import bookmarks",
            settings=test_settings,
            now=1_700_000_000,
        )
        assert consume_confirm_token(
            token,
            user_id=LOCAL_DEFAULT_USER_ID,
            intent=CommandIntent.IMPORT_BOOKMARKS,
            query="import bookmarks",
            settings=test_settings,
            now=1_700_000_000 + 1,
        )
        assert not consume_confirm_token(
            token,
            user_id=LOCAL_DEFAULT_USER_ID,
            intent=CommandIntent.IMPORT_BOOKMARKS,
            query="import bookmarks",
            settings=test_settings,
            now=1_700_000_000 + 2,
        )

    def test_secret_not_derivable_from_app_name_alone(
        self, test_settings: Settings, monkeypatch
    ) -> None:
        """Without AUTH_SECRET, tokens must not verify under the old deterministic formula."""
        monkeypatch.delenv("AUTH_SECRET", raising=False)
        reset_confirm_token_state()
        token = mint_confirm_token(
            user_id="u1",
            intent=CommandIntent.IMPORT_BOOKMARKS,
            query="import bookmarks",
            settings=test_settings,
            now=1_700_000_000,
        )
        assert verify_confirm_token(
            token,
            user_id="u1",
            intent=CommandIntent.IMPORT_BOOKMARKS,
            query="import bookmarks",
            settings=test_settings,
            now=1_700_000_000,
        )
        # Deterministic formula from older builds must not verify.
        import base64
        import hashlib
        import hmac

        qhash = hashlib.sha256(b"import bookmarks").hexdigest()[:16]
        msg = f"u1|import_bookmarks|{qhash}|1700000600"
        weak = f"v1-7-command:{test_settings.app_name}:{test_settings.sqlite_path}"
        sig = hmac.new(weak.encode(), msg.encode(), hashlib.sha256).hexdigest()
        forged = base64.urlsafe_b64encode(f"{msg}|{sig}".encode()).decode()
        assert not verify_confirm_token(
            forged,
            user_id="u1",
            intent=CommandIntent.IMPORT_BOOKMARKS,
            query="import bookmarks",
            settings=test_settings,
            now=1_700_000_000,
        )
        # Different data directory ⇒ different local secret ⇒ token must not verify.
        other_dir = Path(test_settings.sqlite_path).parent / "other_data"
        other_dir.mkdir(parents=True, exist_ok=True)
        other = Settings(
            app_name=test_settings.app_name,
            chroma_persist_dir=str(other_dir / "chroma"),
            chroma_collection_name=test_settings.chroma_collection_name,
            sqlite_path=str(other_dir / "other.db"),
            debug=True,
            auth_enabled=False,
            local_demo_mode=True,
            jobs_enabled=False,
        )
        assert not verify_confirm_token(
            token,
            user_id="u1",
            intent=CommandIntent.IMPORT_BOOKMARKS,
            query="import bookmarks",
            settings=other,
            now=1_700_000_000,
        )


class TestCommandRouterService:
    def test_plan_includes_confirm_for_bulk(self, test_settings: Settings) -> None:
        svc = CommandRouterService(test_settings)
        plan = svc.plan("import bookmarks", user_id=LOCAL_DEFAULT_USER_ID)
        assert plan["requires_confirm"] is True
        assert plan["confirm_token"]
        assert "#imports" in plan["workspace_url"]

    def test_bulk_execute_blocked_without_token(self, test_settings: Settings) -> None:
        svc = CommandRouterService(test_settings)
        out = svc.execute(
            user_id=LOCAL_DEFAULT_USER_ID,
            intent="import_bookmarks",
            query="import bookmarks",
            original_text="import bookmarks",
            confirm_token=None,
        )
        assert out["ok"] is False
        assert out["status"] == "confirm_required"

    def test_bulk_execute_handoff_with_token(self, test_settings: Settings) -> None:
        reset_confirm_token_state()
        svc = CommandRouterService(test_settings)
        plan = svc.plan("import bookmarks", user_id=LOCAL_DEFAULT_USER_ID)
        out = svc.execute(
            user_id=LOCAL_DEFAULT_USER_ID,
            intent="import_bookmarks",
            query=plan["query"],
            original_text="import bookmarks",
            confirm_token=plan["confirm_token"],
        )
        assert out["ok"] is True
        assert out["status"] == "handoff"
        assert "preview" in out["message"].lower()
        # Replay of the same token must fail.
        replay = svc.execute(
            user_id=LOCAL_DEFAULT_USER_ID,
            intent="import_bookmarks",
            query=plan["query"],
            original_text="import bookmarks",
            confirm_token=plan["confirm_token"],
        )
        assert replay["ok"] is False
        assert replay["status"] == "confirm_required"

    def test_search_execute_calls_service(self, test_settings: Settings) -> None:
        svc = CommandRouterService(test_settings)
        mock_resp = MagicMock()
        mock_resp.model_dump.return_value = {
            "query": "MCP",
            "results": [{"title": "Demo", "matched_text": "MCP servers"}],
        }
        with patch("app.services.search_service.SearchService") as MockSearch:
            MockSearch.return_value.search.return_value = mock_resp
            out = svc.execute(
                user_id=LOCAL_DEFAULT_USER_ID,
                intent="search",
                query="MCP",
                original_text="search MCP",
            )
        assert out["ok"] is True
        assert out["status"] == "executed"
        assert out["result"]["results"][0]["title"] == "Demo"


class TestAgentCommandAPI:
    def test_plan_only(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/agent/command",
            json={"text": "search MCP servers", "execute": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["executed"] is False
        assert data["status"] == "planned"
        assert data["plan"]["intent"] == "search"
        assert data["plan"]["query"] == "MCP servers"

    def test_bulk_execute_true_without_token_blocked(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/agent/command",
            json={"text": "import bookmarks", "execute": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["executed"] is False
        assert data["status"] == "confirm_required"
        assert data["plan"]["confirm_token"]

    def test_bulk_execute_endpoint_with_token(self, client: TestClient) -> None:
        planned = client.post(
            "/api/v1/agent/command",
            json={"text": "import playlist", "execute": False},
        ).json()
        token = planned["plan"]["confirm_token"]
        resp = client.post(
            "/api/v1/agent/command/execute",
            json={
                "intent": "import_playlist",
                "query": planned["plan"]["query"],
                "original_text": "import playlist",
                "confirm_token": token,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["executed"] is True
        assert data["status"] == "handoff"
        assert "capture" in (data["result"] or {}).get("workspace_url", "")
        # Successful execute must not re-issue a reusable confirm_token.
        assert data["plan"]["confirm_token"] is None

        replay = client.post(
            "/api/v1/agent/command/execute",
            json={
                "intent": "import_playlist",
                "query": planned["plan"]["query"],
                "original_text": "import playlist",
                "confirm_token": token,
            },
        )
        assert replay.status_code == 200
        assert replay.json()["status"] == "confirm_required"
        # Recovery token may be issued after failed replay.
        assert replay.json()["plan"]["confirm_token"]

    def test_execute_bulk_without_token_via_execute_route(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/agent/command/execute",
            json={
                "intent": "import_bookmarks",
                "query": "import bookmarks",
                "original_text": "import bookmarks",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "confirm_required"

    def test_execute_unknown_intent_400(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/agent/command/execute",
            json={
                "intent": "drop_tables",
                "query": "drop_tables",
                "original_text": "drop_tables",
            },
        )
        assert resp.status_code == 400

    def test_execute_rejects_oversized_query(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/agent/command/execute",
            json={
                "intent": "search",
                "query": "x" * 2500,
                "original_text": "search " + ("x" * 2500),
            },
        )
        assert resp.status_code == 422

    def test_help_execute(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/agent/command",
            json={"text": "help", "execute": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["executed"] is True
        assert "search" in data["message"].lower()

    def test_search_execute_via_api(self, client: TestClient) -> None:
        mock_resp = MagicMock()
        mock_resp.model_dump.return_value = {
            "query": "nonexistent topic xyzzy",
            "results": [],
            "filters_applied": {},
        }
        with patch(
            "app.services.command_router.CommandRouterService.execute"
        ) as mock_exec:
            mock_exec.return_value = {
                "ok": True,
                "status": "executed",
                "message": "Found 0 result(s).",
                "result": mock_resp.model_dump(),
            }
            resp = client.post(
                "/api/v1/agent/command",
                json={"text": "find nonexistent topic xyzzy", "execute": True},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["plan"]["intent"] == "search"
        assert data["status"] == "executed"
        assert data["executed"] is True
        assert data["result"]["results"] == []
        mock_exec.assert_called_once()
