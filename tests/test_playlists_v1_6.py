"""V1-6 playlist preview/ingest API tests (mocked resolver) + error messaging."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.exceptions import AppError
from app.db.job_store import JobStore
from app.db.schema import migrate
from app.main import app
from app.models.user import LOCAL_DEFAULT_USER_ID, UserPublic
from app.services.playlist_service import PlaylistPreviewData, PlaylistVideoEntry
from app.utils.playlist_parser import parse_playlist_url


PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLtestPublicDemo123"


def _preview_data(*, title: str = "AI Tools Course", n: int = 3) -> PlaylistPreviewData:
    info = parse_playlist_url(PLAYLIST_URL)
    entries = [
        PlaylistVideoEntry(
            video_id=f"vid{i}",
            url=f"https://www.youtube.com/watch?v=vid{i}",
            title=f"Lesson {i}",
        )
        for i in range(1, n + 1)
    ]
    return PlaylistPreviewData(
        playlist_id=info.playlist_id,
        canonical_url=info.canonical_url,
        title=title,
        entries=entries,
    )


@pytest.fixture()
def playlist_client(test_settings, monkeypatch):
    from app.api import auth as auth_mod
    from app.api.dependencies import get_app_settings
    from app.config import get_settings

    get_settings.cache_clear()
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_app_settings] = lambda: test_settings
    app.dependency_overrides[auth_mod.get_current_user] = lambda: UserPublic(
        user_id=LOCAL_DEFAULT_USER_ID, display_name="Demo"
    )
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


class TestPlaylistPreviewAPI:
    def test_preview_returns_title_count_samples(self, playlist_client: TestClient) -> None:
        data = _preview_data()
        with patch("app.api.routes.playlists.PlaylistResolver") as mock_cls:
            mock_cls.return_value.preview.return_value = data
            resp = playlist_client.post(
                "/api/v1/playlists/preview",
                json={"playlist_url": PLAYLIST_URL},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["title"] == "AI Tools Course"
        assert body["video_count"] == 3
        assert body["playlist_id"].startswith("PL")
        assert body["sample_titles"] == ["Lesson 1", "Lesson 2", "Lesson 3"]

    def test_preview_clear_error_private(self, playlist_client: TestClient) -> None:
        with patch("app.api.routes.playlists.PlaylistResolver") as mock_cls:
            mock_cls.return_value.preview.side_effect = AppError(
                "Playlist not found or private. Only public playlists can be previewed "
                "without OAuth. Watch Later is not scraped."
            )
            resp = playlist_client.post(
                "/api/v1/playlists/preview",
                json={"playlist_url": PLAYLIST_URL},
            )
        assert resp.status_code == 400
        assert "private" in resp.json()["detail"].lower()

    def test_preview_clear_error_empty(self, playlist_client: TestClient) -> None:
        with patch("app.api.routes.playlists.PlaylistResolver") as mock_cls:
            mock_cls.return_value.preview.side_effect = AppError(
                "Playlist is empty or inaccessible. Only public playlists with videos can be imported."
            )
            resp = playlist_client.post(
                "/api/v1/playlists/preview",
                json={"playlist_url": PLAYLIST_URL},
            )
        assert resp.status_code == 400
        assert "empty" in resp.json()["detail"].lower()

    def test_preview_clear_error_missing_key(self, playlist_client: TestClient) -> None:
        with patch("app.api.routes.playlists.PlaylistResolver") as mock_cls:
            mock_cls.return_value.preview.side_effect = AppError(
                "Could not resolve playlist. Set YOUTUBE_API_KEY for reliable "
                "public playlist preview, or ensure the playlist is public."
            )
            resp = playlist_client.post(
                "/api/v1/playlists/preview",
                json={"playlist_url": PLAYLIST_URL},
            )
        assert resp.status_code == 400
        detail = resp.json()["detail"].lower()
        assert "youtube_api_key" in detail or "api key" in detail


class TestPlaylistIngestAPI:
    def test_ingest_creates_job_with_title_and_flags(
        self, playlist_client: TestClient
    ) -> None:
        from app.models.job import BackgroundJob

        data = _preview_data(title="Demo Playlist", n=2)
        job = BackgroundJob(
            job_id="job-1",
            user_id=LOCAL_DEFAULT_USER_ID,
            job_type="playlist_ingest",
            playlist_id=data.playlist_id,
            playlist_title=data.title,
            total_videos=2,
            queued=2,
            status="queued",
            created_at="2026-07-29T00:00:00Z",
        )

        with (
            patch("app.api.routes.playlists.PlaylistResolver") as mock_resolver,
            patch("app.api.routes.playlists.JobStore") as mock_store,
        ):
            mock_resolver.return_value.preview.return_value = data
            mock_store.return_value.create_playlist_job.return_value = job
            resp = playlist_client.post(
                "/api/v1/playlists/ingest",
                json={
                    "playlist_url": PLAYLIST_URL,
                    "force_refresh": True,
                    "reflection": {
                        "save_reason": "reference",
                        "goal": "Ship V1-6",
                        "reflection_note": "Demo playlist",
                    },
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["playlist_title"] == "Demo Playlist"
        assert body["total_videos"] == 2
        assert body["status"] == "queued"
        kwargs = mock_store.return_value.create_playlist_job.call_args.kwargs
        assert kwargs["force_refresh"] is True
        assert kwargs["playlist_title"] == "Demo Playlist"
        assert kwargs["reflection"] is not None
        assert kwargs["reflection"].goal == "Ship V1-6"

    def test_ingest_rejects_resolver_errors(self, playlist_client: TestClient) -> None:
        with patch("app.api.routes.playlists.PlaylistResolver") as mock_cls:
            mock_cls.return_value.preview.side_effect = AppError(
                "YouTube API key is missing or invalid. Set YOUTUBE_API_KEY and retry."
            )
            resp = playlist_client.post(
                "/api/v1/playlists/ingest",
                json={"playlist_url": PLAYLIST_URL},
            )
        assert resp.status_code == 400
        assert "api key" in resp.json()["detail"].lower()


class TestPlaylistResolverErrors:
    def test_api_private_playlist_message(self) -> None:
        from app.services.playlist_service import PlaylistResolver

        resolver = PlaylistResolver()
        resp = MagicMock()
        resp.status_code = 404
        resp.json.return_value = {
            "error": {
                "message": "The playlist identified with the request's playlistId parameter cannot be found.",
                "errors": [{"reason": "playlistNotFound"}],
            }
        }
        resp.reason_phrase = "Not Found"
        with pytest.raises(AppError) as exc:
            resolver._raise_for_youtube_response(resp, context="playlist items")
        assert "private" in exc.value.message.lower() or "not found" in exc.value.message.lower()

    def test_api_invalid_key_message_403(self) -> None:
        from app.services.playlist_service import PlaylistResolver

        resolver = PlaylistResolver()
        resp = MagicMock()
        resp.status_code = 403
        resp.json.return_value = {
            "error": {
                "message": "API key not valid. Please pass a valid API key.",
                "errors": [{"reason": "keyInvalid"}],
            }
        }
        resp.reason_phrase = "Forbidden"
        with pytest.raises(AppError) as exc:
            resolver._raise_for_youtube_response(resp, context="playlist metadata")
        assert "api key" in exc.value.message.lower()

    def test_api_invalid_key_message_400(self) -> None:
        from app.services.playlist_service import PlaylistResolver

        resolver = PlaylistResolver()
        resp = MagicMock()
        resp.status_code = 400
        resp.json.return_value = {
            "error": {
                "message": "API key not valid. Please pass a valid API key.",
                "errors": [{"reason": "keyInvalid"}],
            }
        }
        resp.reason_phrase = "Bad Request"
        with pytest.raises(AppError) as exc:
            resolver._raise_for_youtube_response(resp, context="playlist metadata")
        assert "api key" in exc.value.message.lower()


class TestWatchLaterRejection:
    def test_watch_later_list_rejected(self) -> None:
        with pytest.raises(AppError) as exc:
            parse_playlist_url("https://www.youtube.com/playlist?list=WL")
        msg = exc.value.message.lower()
        assert "watch later" in msg
        assert "oauth" in msg

    def test_liked_videos_list_rejected(self) -> None:
        with pytest.raises(AppError) as exc:
            parse_playlist_url("https://www.youtube.com/playlist?list=LL")
        assert "oauth" in exc.value.message.lower()

    def test_preview_api_rejects_watch_later(self, playlist_client: TestClient) -> None:
        resp = playlist_client.post(
            "/api/v1/playlists/preview",
            json={"playlist_url": "https://www.youtube.com/playlist?list=WL"},
        )
        assert resp.status_code == 400
        assert "watch later" in resp.json()["detail"].lower()


class TestPlaylistJobControls:
    def test_cancel_pause_retry_flow(self, tmp_path) -> None:
        settings = Settings(sqlite_path=str(tmp_path / "jobs-v16.db"), jobs_enabled=True)
        migrate(settings)
        store = JobStore(settings)
        entries = [
            PlaylistVideoEntry(
                video_id=f"vid{i}",
                url=f"https://www.youtube.com/watch?v=vid{i}",
                title=f"V{i}",
            )
            for i in range(3)
        ]
        job = store.create_playlist_job(
            user_id=LOCAL_DEFAULT_USER_ID,
            playlist_id="PLTEST",
            playlist_title="Cancel Me",
            entries=entries,
            reflection=None,
            force_refresh=False,
        )
        paused = store.set_paused(job.job_id, user_id=LOCAL_DEFAULT_USER_ID, paused=True)
        assert paused.paused is True
        cancelled = store.cancel_job(job.job_id, user_id=LOCAL_DEFAULT_USER_ID)
        assert cancelled.status == "cancelled"
        assert cancelled.paused is True
        with pytest.raises(AppError):
            store.retry_failed(job.job_id, user_id=LOCAL_DEFAULT_USER_ID)
        with pytest.raises(AppError):
            store.set_paused(job.job_id, user_id=LOCAL_DEFAULT_USER_ID, paused=False)

    def test_cancel_http_and_isolation(
        self, playlist_client: TestClient, tmp_path, monkeypatch
    ) -> None:
        from app.api.dependencies import get_app_settings
        from app.config import get_settings

        settings = Settings(
            sqlite_path=str(tmp_path / "jobs-http.db"),
            jobs_enabled=True,
            playlist_max_videos=500,
        )
        migrate(settings)
        get_settings.cache_clear()
        monkeypatch.setattr("app.config.get_settings", lambda: settings)
        monkeypatch.setattr("app.db.job_store.get_settings", lambda: settings)
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_app_settings] = lambda: settings

        store = JobStore(settings)
        job = store.create_playlist_job(
            user_id=LOCAL_DEFAULT_USER_ID,
            playlist_id="PLHTTP",
            playlist_title="HTTP Cancel",
            entries=[
                PlaylistVideoEntry(
                    video_id="v1",
                    url="https://www.youtube.com/watch?v=v1",
                    title="One",
                )
            ],
            reflection=None,
            force_refresh=False,
        )
        resp = playlist_client.post(f"/api/v1/jobs/{job.job_id}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

        # Other user cannot see/cancel
        from app.api import auth as auth_mod

        app.dependency_overrides[auth_mod.get_current_user] = lambda: UserPublic(
            user_id="other-user", display_name="Other"
        )
        missing = playlist_client.post(f"/api/v1/jobs/{job.job_id}/cancel")
        assert missing.status_code == 404

    def test_ingest_respects_max_videos(
        self, playlist_client: TestClient, tmp_path, monkeypatch
    ) -> None:
        from app.config import get_settings

        settings = Settings(
            sqlite_path=str(tmp_path / "max.db"),
            jobs_enabled=True,
            playlist_max_videos=2,
        )
        get_settings.cache_clear()
        monkeypatch.setattr("app.config.get_settings", lambda: settings)
        app.dependency_overrides[get_settings] = lambda: settings
        data = _preview_data(n=3)
        with patch("app.api.routes.playlists.PlaylistResolver") as mock_resolver:
            mock_resolver.return_value.preview.return_value = data
            resp = playlist_client.post(
                "/api/v1/playlists/ingest",
                json={"playlist_url": PLAYLIST_URL},
            )
        assert resp.status_code == 400
        assert "limit" in resp.json()["detail"].lower()


class TestPreviewCache:
    def test_second_preview_reuses_cache(self) -> None:
        from app.services import playlist_service as ps

        ps._preview_cache.clear()
        data = _preview_data(title="Cached", n=2)
        with patch.object(ps.PlaylistResolver, "_fetch_all", return_value=(data.title, data.entries)) as fetch:
            resolver = ps.PlaylistResolver()
            first = resolver.preview(PLAYLIST_URL)
            second = resolver.preview(PLAYLIST_URL)
        assert first.title == "Cached"
        assert second.playlist_id == first.playlist_id
        assert fetch.call_count == 1


class TestAtomicClaim:
    def test_claim_marks_processing_once(self, tmp_path) -> None:
        settings = Settings(sqlite_path=str(tmp_path / "claim.db"), jobs_enabled=True)
        migrate(settings)
        store = JobStore(settings)
        job = store.create_playlist_job(
            user_id=LOCAL_DEFAULT_USER_ID,
            playlist_id="PLCLAIM",
            playlist_title="Claim",
            entries=[
                PlaylistVideoEntry(
                    video_id="only",
                    url="https://www.youtube.com/watch?v=only",
                    title="Only",
                )
            ],
            reflection=None,
            force_refresh=False,
        )
        first = store.claim_next_item(worker_id="w1")
        second = store.claim_next_item(worker_id="w2")
        assert first is not None
        assert first[0] == job.job_id
        assert second is None


class TestExtensionV16Helpers:
    def test_workspace_deep_link_normalization(self) -> None:
        # Python mirror of extension/popup.js workspaceDeepLink
        def workspace_deep_link(pwa_url: str, hash_frag: str) -> str:
            base = str(pwa_url or "http://127.0.0.1:8000/").strip().rstrip("/") + "/"
            frag = hash_frag if hash_frag.startswith("#") else f"#{hash_frag}"
            return f"{base}{frag}"

        assert (
            workspace_deep_link("http://127.0.0.1:8000", "#capture")
            == "http://127.0.0.1:8000/#capture"
        )
        assert (
            workspace_deep_link("http://127.0.0.1:8000/", "capture")
            == "http://127.0.0.1:8000/#capture"
        )
        assert (
            workspace_deep_link("http://127.0.0.1:8000///", "#ask")
            == "http://127.0.0.1:8000/#ask"
        )
