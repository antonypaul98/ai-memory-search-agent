"""YouTube playlist URL parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from app.core.exceptions import AppError

_PLAYLIST_ID = re.compile(r"^(PL|UU|OLAK|RD|FL)[\w-]+$")
# Watch Later (WL) and Liked videos (LL) require Google OAuth — never scrape.
_AUTH_REQUIRED_LIST_IDS = frozenset({"WL", "LL"})


@dataclass(frozen=True)
class PlaylistUrlInfo:
    playlist_id: str
    canonical_url: str


def parse_playlist_url(url: str) -> PlaylistUrlInfo:
    if not url or not url.strip():
        raise AppError("Playlist URL cannot be empty.")
    normalized = url.strip()
    if not normalized.startswith(("http://", "https://")):
        normalized = f"https://{normalized}"
    parsed = urlparse(normalized)
    host = (parsed.hostname or "").lower().replace("www.", "")
    if host not in ("youtube.com", "m.youtube.com"):
        raise AppError("Not a YouTube playlist URL.")
    playlist_id = parse_qs(parsed.query).get("list", [None])[0]
    if not playlist_id:
        raise AppError("Could not extract a valid playlist ID.")
    if playlist_id.upper() in _AUTH_REQUIRED_LIST_IDS:
        raise AppError(
            "Watch Later and Liked videos require Google OAuth and are not available "
            "in V1. Use a public playlist URL instead."
        )
    if not _PLAYLIST_ID.match(playlist_id):
        raise AppError("Could not extract a valid playlist ID.")
    canonical = f"https://www.youtube.com/playlist?list={playlist_id}"
    return PlaylistUrlInfo(playlist_id=playlist_id, canonical_url=canonical)
