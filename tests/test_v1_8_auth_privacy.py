"""V1-8 auth isolation, export/delete, rate limiting, privacy page."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.core.rate_limit import reset_rate_limiter
from app.db.memory_store import MemoryStore, reset_memory_store_cache
from app.db.schema import SCHEMA_VERSION, migrate
from app.db.video_registry import VideoRegistry, reset_video_registry_cache
from app.models.lifecycle import MemoryLifecycleState
from app.models.user import LOCAL_DEFAULT_USER_ID, UserPublic
from app.models.video import SourceType
from app.services.privacy_service import PrivacyService


def _auth_settings(tmp_path, **kwargs) -> Settings:
    chroma_dir = tmp_path / "chroma"
    base = dict(
        app_name="AI Memory Search Agent (test)",
        chroma_persist_dir=str(chroma_dir),
        chroma_collection_name="test_memory_items",
        sqlite_path=str(tmp_path / "auth.db"),
        debug=True,
        hierarchical_retrieval_enabled=False,
        semantic_cache_enabled=False,
        jobs_enabled=False,
        pwa_enabled=True,
        auth_enabled=True,
        local_demo_mode=False,
        rate_limit_enabled=False,
        schema_version=SCHEMA_VERSION,
    )
    base.update(kwargs)
    return Settings(**base)


def _client_for(settings: Settings) -> TestClient:
    from app.api.auth import get_current_user
    from app.api.dependencies import get_app_settings, get_health_service
    from app.db.repositories.memory_repository import MemoryRepository
    from app.main import app
    from app.services.health_service import HealthService

    get_settings.cache_clear()
    app.dependency_overrides.clear()

    def _override_settings() -> Settings:
        return settings

    app.dependency_overrides[get_settings] = _override_settings
    app.dependency_overrides[get_app_settings] = _override_settings
    # Do NOT override get_current_user — exercise real auth.
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides[get_health_service] = lambda: HealthService(
        settings=settings,
        repository=MemoryRepository(settings),
    )
    return TestClient(app)


class TestAuthIntegration:
    def test_register_login_me_logout(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("AUTH_SECRET", "test-secret-v1-8")
        settings = _auth_settings(tmp_path)
        migrate(settings)
        with patch("app.main.get_settings", lambda: settings):
            client = _client_for(settings)
            with client:
                denied = client.get("/api/v1/auth/me")
                assert denied.status_code == 401

                reg = client.post(
                    "/api/v1/auth/register",
                    json={
                        "email": "alice@example.com",
                        "password": "password123",
                        "display_name": "Alice",
                    },
                )
                assert reg.status_code == 200
                token = reg.json()["token"]
                assert token

                me = client.get(
                    "/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert me.status_code == 200
                assert me.json()["email"] == "alice@example.com"

                login = client.post(
                    "/api/v1/auth/login",
                    json={"email": "alice@example.com", "password": "password123"},
                )
                assert login.status_code == 200
                token2 = login.json()["token"]

                out = client.post(
                    "/api/v1/auth/logout",
                    headers={"Authorization": f"Bearer {token2}"},
                )
                assert out.status_code == 200
                assert out.json()["logged_out"] is True

                me2 = client.get(
                    "/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {token2}"},
                )
                assert me2.status_code == 401

            from app.main import app

            app.dependency_overrides.clear()

    def test_register_disabled_when_auth_off(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/auth/register",
            json={"email": "x@y.com", "password": "password123", "display_name": "X"},
        )
        assert resp.status_code == 403


class TestTenantIsolation:
    def test_registry_composite_key_isolation(self, tmp_path) -> None:
        settings = Settings(sqlite_path=str(tmp_path / "reg.db"))
        migrate(settings)
        reset_video_registry_cache()
        reg = VideoRegistry(settings)
        reg.upsert_video(
            video_id="samevid",
            url="https://www.youtube.com/watch?v=samevid",
            title="A",
            channel="Ch",
            user_id="user-a",
        )
        reg.upsert_video(
            video_id="samevid",
            url="https://www.youtube.com/watch?v=samevid",
            title="B",
            channel="Ch",
            user_id="user-b",
        )
        assert reg.get_video("samevid", user_id="user-a")["title"] == "A"
        assert reg.get_video("samevid", user_id="user-b")["title"] == "B"
        assert reg.get_video("samevid", user_id="user-a") is not None
        assert reg.is_indexed("samevid", user_id="user-c") is False

    def test_memory_not_visible_cross_user(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("AUTH_SECRET", "test-secret-v1-8")
        settings = _auth_settings(tmp_path)
        migrate(settings)
        reset_memory_store_cache()
        store = MemoryStore(settings)
        mem_a = store.upsert(
            user_id="user-a",
            source_type=SourceType.WEB,
            external_id="ext-a",
            canonical_url="https://example.com/a",
            title="Alpha",
            lifecycle_state=MemoryLifecycleState.TRUSTED,
        )
        store.upsert(
            user_id="user-b",
            source_type=SourceType.WEB,
            external_id="ext-b",
            canonical_url="https://example.com/b",
            title="Beta",
            lifecycle_state=MemoryLifecycleState.TRUSTED,
        )
        assert store.get(mem_a.memory_id, user_id="user-b") is None
        assert store.get(mem_a.memory_id, user_id="user-a") is not None
        assert len(store.list_recent(user_id="user-a", limit=10)) == 1
        assert store.list_recent(user_id="user-a", limit=10)[0].title == "Alpha"


class TestExportDelete:
    def test_export_and_delete_memory(self, tmp_path) -> None:
        settings = Settings(
            sqlite_path=str(tmp_path / "priv.db"),
            chroma_persist_dir=str(tmp_path / "chroma"),
            hierarchical_retrieval_enabled=False,
            semantic_cache_enabled=False,
        )
        migrate(settings)
        reset_memory_store_cache()
        reset_video_registry_cache()
        store = MemoryStore(settings)
        mem = store.upsert(
            user_id=LOCAL_DEFAULT_USER_ID,
            source_type=SourceType.WEB,
            external_id="exp1",
            canonical_url="https://example.com/exp1",
            title="Export Me",
            lifecycle_state=MemoryLifecycleState.TRUSTED,
        )
        privacy = PrivacyService(settings)
        export = privacy.export_user_data(user_id=LOCAL_DEFAULT_USER_ID)
        assert export["export_version"] == 1
        assert any(m["memory_id"] == mem.memory_id for m in export["memories"])

        result = privacy.delete_memory(memory_id=mem.memory_id, user_id=LOCAL_DEFAULT_USER_ID)
        assert result["deleted"] is True
        assert store.get(mem.memory_id, user_id=LOCAL_DEFAULT_USER_ID) is None

    def test_delete_http_isolation(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("AUTH_SECRET", "test-secret-v1-8")
        settings = _auth_settings(tmp_path)
        migrate(settings)
        reset_memory_store_cache()
        store = MemoryStore(settings)
        mem = store.upsert(
            user_id="alice_at_example.com",
            source_type=SourceType.WEB,
            external_id="iso1",
            canonical_url="https://example.com/iso1",
            title="Secret",
            lifecycle_state=MemoryLifecycleState.TRUSTED,
        )
        with patch("app.main.get_settings", lambda: settings):
            client = _client_for(settings)
            with client:
                bob = client.post(
                    "/api/v1/auth/register",
                    json={
                        "email": "bob@example.com",
                        "password": "password123",
                        "display_name": "Bob",
                    },
                )
                bob_token = bob.json()["token"]
                # Alice registers separately so Bob cannot delete Alice's memory
                alice = client.post(
                    "/api/v1/auth/register",
                    json={
                        "email": "alice@example.com",
                        "password": "password123",
                        "display_name": "Alice",
                    },
                )
                assert alice.status_code == 200
                # Memory was created with user_id matching alice's id convention
                denied = client.delete(
                    f"/api/v1/memories/{mem.memory_id}",
                    headers={"Authorization": f"Bearer {bob_token}"},
                )
                assert denied.status_code == 404
                assert store.get(mem.memory_id, user_id="alice_at_example.com") is not None

                alice_token = alice.json()["token"]
                ok = client.delete(
                    f"/api/v1/memories/{mem.memory_id}",
                    headers={"Authorization": f"Bearer {alice_token}"},
                )
                assert ok.status_code == 200
                assert store.get(mem.memory_id, user_id="alice_at_example.com") is None

            from app.main import app

            app.dependency_overrides.clear()

    def test_export_http(self, client: TestClient) -> None:
        resp = client.get("/api/v1/privacy/export")
        assert resp.status_code == 200
        body = resp.json()
        assert body["export_version"] == 1
        assert "memories" in body


class TestRateLimitAndPrivacyPage:
    def test_privacy_page(self, client: TestClient) -> None:
        resp = client.get("/privacy")
        assert resp.status_code == 200
        assert "Privacy Policy" in resp.text
        assert "AI Memory Agent" in resp.text
        disclosure = client.get("/static/privacy-disclosure.txt")
        assert disclosure.status_code == 200
        assert "Single purpose" in disclosure.text

    def test_rate_limit_returns_429(self, tmp_path) -> None:
        settings = Settings(
            sqlite_path=str(tmp_path / "rl.db"),
            chroma_persist_dir=str(tmp_path / "chroma"),
            rate_limit_enabled=True,
            rate_limit_requests=3,
            rate_limit_window_sec=60,
            auth_enabled=False,
            jobs_enabled=False,
            hierarchical_retrieval_enabled=False,
        )
        migrate(settings)
        reset_rate_limiter()
        from app.api.auth import get_current_user
        from app.api.dependencies import get_app_settings, get_health_service
        from app.db.repositories.memory_repository import MemoryRepository
        from app.main import app
        from app.services.health_service import HealthService

        get_settings.cache_clear()
        app.dependency_overrides.clear()
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_app_settings] = lambda: settings
        app.dependency_overrides[get_current_user] = lambda: UserPublic(
            user_id=LOCAL_DEFAULT_USER_ID, display_name="Local Demo User"
        )
        app.dependency_overrides[get_health_service] = lambda: HealthService(
            settings=settings,
            repository=MemoryRepository(settings),
        )
        with patch("app.main.get_settings", lambda: settings):
            with patch("app.middleware.rate_limit.get_settings", lambda: settings):
                with TestClient(app) as client:
                    codes = []
                    for _ in range(5):
                        codes.append(client.get("/api/v1/health").status_code)
                    assert 429 in codes
                    assert codes.count(200) >= 1
        app.dependency_overrides.clear()
        reset_rate_limiter()

    def test_pwa_config_exposes_privacy(self, client: TestClient) -> None:
        resp = client.get("/api/v1/pwa/config")
        assert resp.status_code == 200
        assert resp.json()["privacy_policy_url"] == "/privacy"


class TestSchemaV9:
    def test_migrate_to_v9(self, tmp_path) -> None:
        settings = Settings(sqlite_path=str(tmp_path / "v9.db"))
        migrate(settings)
        import sqlite3

        conn = sqlite3.connect(settings.sqlite_path)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == SCHEMA_VERSION
        pk = [
            row[1]
            for row in conn.execute("PRAGMA table_info(video_registry)").fetchall()
            if row[5]
        ]
        assert "user_id" in pk and "video_id" in pk
        conn.close()

    def test_migrate_v8_registry_preserves_rows(self, tmp_path) -> None:
        """Old video_id-only PK rows migrate into composite (user_id, video_id)."""
        import sqlite3

        db = tmp_path / "legacy.db"
        conn = sqlite3.connect(db)
        conn.executescript(
            """
            PRAGMA user_version = 8;
            CREATE TABLE video_registry (
                video_id TEXT PRIMARY KEY,
                url TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '',
                saved_at TEXT NOT NULL,
                last_viewed TEXT,
                view_count INTEGER NOT NULL DEFAULT 0,
                search_count INTEGER NOT NULL DEFAULT 0,
                last_searched TEXT,
                helpful_count INTEGER NOT NULL DEFAULT 0,
                not_helpful_count INTEGER NOT NULL DEFAULT 0,
                user_id TEXT NOT NULL DEFAULT 'local-default'
            );
            INSERT INTO video_registry (video_id, url, title, channel, saved_at, user_id)
            VALUES ('vid1', 'https://example.com/v1', 'Legacy', 'Ch', '2026-01-01T00:00:00+00:00', 'alice');
            """
        )
        conn.close()

        settings = Settings(sqlite_path=str(db))
        migrate(settings)
        conn = sqlite3.connect(db)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == SCHEMA_VERSION
        pk = {
            row[1]
            for row in conn.execute("PRAGMA table_info(video_registry)").fetchall()
            if row[5]
        }
        assert pk == {"user_id", "video_id"}
        row = conn.execute(
            "SELECT title, user_id FROM video_registry WHERE video_id = ?",
            ("vid1",),
        ).fetchone()
        assert row is not None
        assert row[0] == "Legacy"
        assert row[1] == "alice"
        conn.close()


class TestSessionLifecycle:
    def test_expired_session_rejected(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("AUTH_SECRET", "test-secret-v1-8")
        settings = _auth_settings(tmp_path, session_ttl_hours=168)
        migrate(settings)
        from datetime import datetime, timedelta, timezone

        from app.db.auth_store import AuthStore
        from app.db.schema import get_connection

        store = AuthStore(settings)
        user = store.create_user(
            email="expire@example.com",
            password="password123",
            display_name="Expire",
        )
        token = store.create_session(user.user_id)
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with get_connection(settings) as conn:
            conn.execute(
                "UPDATE sessions SET expires_at = ? WHERE token = ?",
                (past, token),
            )
        assert store.resolve_token(token) is None
        with get_connection(settings) as conn:
            left = conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE token = ?", (token,)
            ).fetchone()[0]
        assert left == 0

    def test_logout_clears_cookie_and_revokes(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("AUTH_SECRET", "test-secret-v1-8")
        settings = _auth_settings(tmp_path)
        migrate(settings)
        with patch("app.main.get_settings", lambda: settings):
            client = _client_for(settings)
            with client:
                login = client.post(
                    "/api/v1/auth/register",
                    json={
                        "email": "cookie@example.com",
                        "password": "password123",
                        "display_name": "Cookie",
                    },
                )
                assert login.status_code == 200
                token = login.json()["token"]
                assert client.cookies.get("session_token")

                out = client.post(
                    "/api/v1/auth/logout",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert out.status_code == 200
                # TestClient may retain jar entry; server must reject the token.
                me = client.get(
                    "/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert me.status_code == 401

            from app.main import app

            app.dependency_overrides.clear()

    def test_invalid_email_rejected(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("AUTH_SECRET", "test-secret-v1-8")
        settings = _auth_settings(tmp_path)
        migrate(settings)
        with patch("app.main.get_settings", lambda: settings):
            client = _client_for(settings)
            with client:
                bad = client.post(
                    "/api/v1/auth/register",
                    json={
                        "email": "not-an-email",
                        "password": "password123",
                        "display_name": "Bad",
                    },
                )
                assert bad.status_code == 422

            from app.main import app

            app.dependency_overrides.clear()

    def test_privacy_requires_auth_when_enabled(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("AUTH_SECRET", "test-secret-v1-8")
        settings = _auth_settings(tmp_path)
        migrate(settings)
        with patch("app.main.get_settings", lambda: settings):
            client = _client_for(settings)
            with client:
                assert client.get("/api/v1/privacy/export").status_code == 401
                assert client.delete("/api/v1/privacy/memories").status_code == 401

            from app.main import app

            app.dependency_overrides.clear()


class TestCapsuleTenantSafety:
    def test_delete_does_not_drop_shared_capsule(self, tmp_path) -> None:
        from app.db.schema import get_connection

        settings = Settings(
            sqlite_path=str(tmp_path / "cap.db"),
            chroma_persist_dir=str(tmp_path / "chroma"),
            hierarchical_retrieval_enabled=False,
            semantic_cache_enabled=False,
        )
        migrate(settings)
        reset_memory_store_cache()
        reset_video_registry_cache()
        store = MemoryStore(settings)
        reg = VideoRegistry(settings)
        shared_id = "sharedvid123"
        mem_a = store.upsert(
            user_id="user-a",
            source_type=SourceType.YOUTUBE,
            external_id=shared_id,
            canonical_url=f"https://www.youtube.com/watch?v={shared_id}",
            title="A",
            lifecycle_state=MemoryLifecycleState.TRUSTED,
        )
        store.upsert(
            user_id="user-b",
            source_type=SourceType.YOUTUBE,
            external_id=shared_id,
            canonical_url=f"https://www.youtube.com/watch?v={shared_id}",
            title="B",
            lifecycle_state=MemoryLifecycleState.TRUSTED,
        )
        reg.upsert_video(
            video_id=shared_id,
            url=f"https://www.youtube.com/watch?v={shared_id}",
            title="A",
            channel="Ch",
            user_id="user-a",
        )
        reg.upsert_video(
            video_id=shared_id,
            url=f"https://www.youtube.com/watch?v={shared_id}",
            title="B",
            channel="Ch",
            user_id="user-b",
        )
        with get_connection(settings) as conn:
            conn.execute(
                """
                INSERT INTO memory_capsules_json (video_id, capsule_json, updated_at)
                VALUES (?, ?, ?)
                """,
                (shared_id, '{"summary":"keep-me"}', "2026-07-30T00:00:00+00:00"),
            )

        privacy = PrivacyService(settings)
        privacy.delete_memory(memory_id=mem_a.memory_id, user_id="user-a")

        with get_connection(settings) as conn:
            row = conn.execute(
                "SELECT capsule_json FROM memory_capsules_json WHERE video_id = ?",
                (shared_id,),
            ).fetchone()
        assert row is not None
        assert "keep-me" in row[0]
        assert store.get(mem_a.memory_id, user_id="user-a") is None
        assert (
            store.get_by_external(
                user_id="user-b",
                source_type=SourceType.YOUTUBE,
                external_id=shared_id,
            )
            is not None
        )


class TestRateLimitBypass:
    def test_rotating_bearer_does_not_bypass(self, tmp_path) -> None:
        settings = Settings(
            sqlite_path=str(tmp_path / "rl2.db"),
            chroma_persist_dir=str(tmp_path / "chroma"),
            rate_limit_enabled=True,
            rate_limit_requests=3,
            rate_limit_window_sec=60,
            auth_enabled=False,
            jobs_enabled=False,
            hierarchical_retrieval_enabled=False,
        )
        migrate(settings)
        reset_rate_limiter()
        from app.api.auth import get_current_user
        from app.api.dependencies import get_app_settings, get_health_service
        from app.db.repositories.memory_repository import MemoryRepository
        from app.main import app
        from app.services.health_service import HealthService

        get_settings.cache_clear()
        app.dependency_overrides.clear()
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_app_settings] = lambda: settings
        app.dependency_overrides[get_current_user] = lambda: UserPublic(
            user_id=LOCAL_DEFAULT_USER_ID, display_name="Local Demo User"
        )
        app.dependency_overrides[get_health_service] = lambda: HealthService(
            settings=settings,
            repository=MemoryRepository(settings),
        )
        with patch("app.main.get_settings", lambda: settings):
            with patch("app.middleware.rate_limit.get_settings", lambda: settings):
                with TestClient(app) as client:
                    codes = []
                    for i in range(6):
                        codes.append(
                            client.get(
                                "/api/v1/health",
                                headers={"Authorization": f"Bearer forged-token-{i}-xxxx"},
                            ).status_code
                        )
                    assert 429 in codes
        app.dependency_overrides.clear()
        reset_rate_limiter()

    def test_privacy_page_exempt_from_rate_limit(self, tmp_path) -> None:
        settings = Settings(
            sqlite_path=str(tmp_path / "rl3.db"),
            chroma_persist_dir=str(tmp_path / "chroma"),
            rate_limit_enabled=True,
            rate_limit_requests=2,
            rate_limit_window_sec=60,
            auth_enabled=False,
            jobs_enabled=False,
            hierarchical_retrieval_enabled=False,
        )
        migrate(settings)
        reset_rate_limiter()
        from app.api.dependencies import get_app_settings
        from app.main import app

        get_settings.cache_clear()
        app.dependency_overrides.clear()
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_app_settings] = lambda: settings
        with patch("app.main.get_settings", lambda: settings):
            with patch("app.middleware.rate_limit.get_settings", lambda: settings):
                with TestClient(app) as client:
                    for _ in range(5):
                        assert client.get("/privacy").status_code == 200
        app.dependency_overrides.clear()
        reset_rate_limiter()
