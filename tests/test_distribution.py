"""Distribution layer tests: PWA, jobs, playlists, auth isolation, SSRF."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.job_store import JobStore
from app.db.schema import migrate
from app.models.user import LOCAL_DEFAULT_USER_ID
from app.services.playlist_service import PlaylistVideoEntry
from app.core.exceptions import AppError
from app.services.ssrf_fetch import validate_public_http_url
from app.utils.playlist_parser import parse_playlist_url


class TestPWA:
    def test_manifest_and_service_worker(self, client: TestClient) -> None:
        manifest = client.get("/manifest.webmanifest")
        assert manifest.status_code == 200
        assert "AI Memory" in manifest.text
        sw = client.get("/sw.js")
        assert sw.status_code == 200
        assert "fetch" in sw.text

    def test_pwa_config(self, client: TestClient) -> None:
        resp = client.get("/api/v1/pwa/config")
        assert resp.status_code == 200
        assert resp.json()["pwa_enabled"] is True


class TestPlaylistParser:
    def test_parse_playlist_url(self) -> None:
        info = parse_playlist_url("https://www.youtube.com/playlist?list=PL1234567890")
        assert info.playlist_id.startswith("PL")

    def test_rejects_watch_later(self) -> None:
        with pytest.raises(AppError) as exc:
            parse_playlist_url("https://www.youtube.com/playlist?list=WL")
        assert "watch later" in exc.value.message.lower()


class TestJobStore:
    def test_create_and_resume_job(self, tmp_path) -> None:
        settings = Settings(sqlite_path=str(tmp_path / "jobs.db"), jobs_enabled=True)
        migrate(settings)
        store = JobStore(settings)
        entries = [
            PlaylistVideoEntry(video_id=f"vid{i}", url=f"https://www.youtube.com/watch?v=vid{i}", title=f"V{i}")
            for i in range(5)
        ]
        job = store.create_playlist_job(
            user_id=LOCAL_DEFAULT_USER_ID,
            playlist_id="PLTEST",
            playlist_title="Test",
            entries=entries,
            reflection=None,
            force_refresh=False,
        )
        assert job.total_videos == 5
        paused = store.set_paused(job.job_id, user_id=LOCAL_DEFAULT_USER_ID, paused=True)
        assert paused.paused is True
        detail = store.get_job_detail(job.job_id, user_id=LOCAL_DEFAULT_USER_ID)
        assert len(detail.items) == 5


class TestUserIsolation:
    def test_job_not_visible_to_other_user(self, tmp_path) -> None:
        settings = Settings(sqlite_path=str(tmp_path / "iso.db"))
        store = JobStore(settings)
        job = store.create_playlist_job(
            user_id="user-a",
            playlist_id="PLX",
            playlist_title="X",
            entries=[PlaylistVideoEntry(video_id="v1", url="https://www.youtube.com/watch?v=v1", title="T")],
            reflection=None,
            force_refresh=False,
        )
        with pytest.raises(KeyError):
            store.get_job(job.job_id, user_id="user-b")


class TestSSRF:
    def test_blocks_private_hosts(self) -> None:
        with pytest.raises(AppError):
            validate_public_http_url("http://127.0.0.1/secret")

    def test_allows_public_https(self) -> None:
        assert validate_public_http_url("https://example.com/article").startswith("https://")


class TestCaptureAPI:
    def test_capture_youtube_payload(self, client: TestClient) -> None:
        with patch("app.services.capture_service.IngestService") as mock_ingest:
            instance = mock_ingest.return_value
            instance.ingest_single_url.return_value = MagicMock(success=True, skipped=False, error=None)
            resp = client.post(
                "/api/v1/capture/url",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "title": "Demo"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] in {"completed", "stored", "queued", "processing", "embedding"}


class TestPlaylistPagination:
    def test_mock_large_playlist(self) -> None:
        from app.services.playlist_service import _dedupe_entries

        entries = [
            PlaylistVideoEntry(video_id=f"vid{i}", url=f"https://youtu.be/vid{i}", title=str(i))
            for i in range(250)
        ]
        entries.append(entries[0])
        deduped = _dedupe_entries(entries)
        assert len(deduped) == 250
