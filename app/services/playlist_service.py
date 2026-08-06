"""Resolve playlist entries via YouTube Data API or yt-dlp fallback."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import httpx

from app.config import Settings, get_settings
from app.core.exceptions import AppError
from app.utils.playlist_parser import PlaylistUrlInfo, parse_playlist_url
from app.utils.url_parser import is_valid_youtube_url

# Short TTL so preview → confirm does not re-fetch the full playlist twice.
_PREVIEW_CACHE_TTL_SEC = 90.0
_preview_cache: dict[str, tuple[float, "PlaylistPreviewData"]] = {}


@dataclass(frozen=True)
class PlaylistVideoEntry:
    video_id: str
    url: str
    title: str


@dataclass(frozen=True)
class PlaylistPreviewData:
    playlist_id: str
    canonical_url: str
    title: str
    entries: list[PlaylistVideoEntry]


class PlaylistResolver:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def preview(self, playlist_url: str) -> PlaylistPreviewData:
        info = parse_playlist_url(playlist_url)
        cached = _preview_cache.get(info.playlist_id)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        title, entries = self._fetch_all(info)
        data = PlaylistPreviewData(
            playlist_id=info.playlist_id,
            canonical_url=info.canonical_url,
            title=title or info.playlist_id,
            entries=entries,
        )
        _preview_cache[info.playlist_id] = (time.monotonic() + _PREVIEW_CACHE_TTL_SEC, data)
        return data

    def _fetch_all(self, info: PlaylistUrlInfo) -> tuple[str, list[PlaylistVideoEntry]]:
        api_key = os.environ.get(self._settings.youtube_api_key_env, "").strip()
        if api_key:
            try:
                return self._fetch_via_api(info, api_key)
            except AppError:
                raise
            except Exception as exc:
                if not self._settings.local_demo_mode:
                    raise AppError(f"YouTube API playlist fetch failed: {exc}") from exc
        try:
            return self._fetch_via_ytdlp(info)
        except AppError:
            raise
        except Exception as exc:
            if not api_key:
                raise AppError(
                    "Could not resolve playlist. Set YOUTUBE_API_KEY for reliable "
                    "public playlist preview, or ensure the playlist is public."
                ) from exc
            raise AppError(
                "Could not read playlist. It may be private, empty, or unavailable."
            ) from exc

    def _fetch_via_api(
        self, info: PlaylistUrlInfo, api_key: str
    ) -> tuple[str, list[PlaylistVideoEntry]]:
        title = self._fetch_playlist_title(info.playlist_id, api_key)
        entries: list[PlaylistVideoEntry] = []
        page_token = ""
        base = "https://www.googleapis.com/youtube/v3/playlistItems"
        with httpx.Client(timeout=30.0) as client:
            while True:
                params = {
                    "part": "snippet,contentDetails",
                    "playlistId": info.playlist_id,
                    "maxResults": min(50, self._settings.playlist_page_size),
                    "key": api_key,
                }
                if page_token:
                    params["pageToken"] = page_token
                resp = client.get(base, params=params)
                self._raise_for_youtube_response(resp, context="playlist items")
                data = resp.json()
                for item in data.get("items", []):
                    vid = item.get("contentDetails", {}).get("videoId") or ""
                    item_title = item.get("snippet", {}).get("title") or ""
                    if not vid:
                        continue
                    entries.append(
                        PlaylistVideoEntry(
                            video_id=vid,
                            url=f"https://www.youtube.com/watch?v={vid}",
                            title=item_title,
                        )
                    )
                page_token = data.get("nextPageToken") or ""
                if not page_token:
                    break
        if not entries:
            raise AppError(
                "Playlist is empty or inaccessible. Only public playlists with videos can be imported."
            )
        return title or info.playlist_id, _dedupe_entries(entries)

    def _fetch_playlist_title(self, playlist_id: str, api_key: str) -> str:
        url = "https://www.googleapis.com/youtube/v3/playlists"
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(
                url,
                params={"part": "snippet", "id": playlist_id, "key": api_key},
            )
            self._raise_for_youtube_response(resp, context="playlist metadata")
            items = resp.json().get("items") or []
            if not items:
                # Empty items usually means private / deleted / wrong id with a valid key.
                raise AppError(
                    "Playlist not found or private. Use a public playlist URL "
                    "(Watch Later requires Google OAuth and is not available in V1)."
                )
            return (items[0].get("snippet") or {}).get("title") or ""

    def _raise_for_youtube_response(self, resp: httpx.Response, *, context: str) -> None:
        if resp.status_code < 400:
            return
        detail = ""
        try:
            payload = resp.json()
            err = payload.get("error") or {}
            detail = err.get("message") or ""
            reasons = [
                (e.get("reason") or "") for e in (err.get("errors") or []) if isinstance(e, dict)
            ]
        except Exception:
            reasons = []
            detail = (resp.text or "")[:200]

        reason_blob = " ".join(reasons).lower()
        detail_l = detail.lower()
        key_invalid = (
            "keyinvalid" in reason_blob.replace("_", "")
            or "apikeyinvalid" in reason_blob.replace("_", "")
            or "api key not valid" in detail_l
        )
        if resp.status_code in {400, 401, 403} and key_invalid:
            raise AppError(
                "YouTube API key is missing or invalid. Set YOUTUBE_API_KEY and retry."
            )
        if resp.status_code in {403, 404} or "playlistnotfound" in reason_blob.replace(
            "_", ""
        ):
            raise AppError(
                "Playlist not found or private. Only public playlists can be previewed "
                "without OAuth. Watch Later is not scraped."
            )
        if resp.status_code == 400 and "invalid" in detail_l:
            raise AppError(f"Invalid playlist request ({context}): {detail or resp.status_code}")
        raise AppError(
            f"YouTube API {context} failed ({resp.status_code}): {detail or resp.reason_phrase}"
        )

    def _fetch_via_ytdlp(self, info: PlaylistUrlInfo) -> tuple[str, list[PlaylistVideoEntry]]:
        import yt_dlp

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
            "ignoreerrors": True,
        }
        entries: list[PlaylistVideoEntry] = []
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                data = ydl.extract_info(info.canonical_url, download=False)
        except Exception as exc:
            raise AppError(
                "Could not read playlist. Private playlists and Watch Later require "
                "authorized access (not available in V1). Use a public playlist URL."
            ) from exc
        if not data:
            raise AppError("Playlist metadata unavailable.")
        title = data.get("title") or info.playlist_id
        for item in data.get("entries") or []:
            if not item:
                continue
            vid = item.get("id") or ""
            if not vid or vid.startswith("PL"):
                continue
            url = item.get("url") or item.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}"
            if not is_valid_youtube_url(url):
                continue
            entries.append(
                PlaylistVideoEntry(
                    video_id=vid,
                    url=url,
                    title=item.get("title") or "",
                )
            )
        if not entries:
            raise AppError(
                "No public videos found in playlist. Empty or private playlists cannot be imported."
            )
        return title, _dedupe_entries(entries)


def _dedupe_entries(entries: list[PlaylistVideoEntry]) -> list[PlaylistVideoEntry]:
    seen: set[str] = set()
    out: list[PlaylistVideoEntry] = []
    for entry in entries:
        if entry.video_id in seen:
            continue
        seen.add(entry.video_id)
        out.append(entry)
    return out
