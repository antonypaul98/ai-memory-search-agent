"""
YouTube URL parsing and validation.

Pure functions — no HTTP calls, no database access.
Used by TranscriptService and (Phase 3+) ingest pipeline.
"""

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from app.core.exceptions import InvalidYouTubeURLError

# YouTube video IDs are always 11 characters.
_VIDEO_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{11}$")

# Path-based URL patterns: youtu.be/ID, /embed/ID, /shorts/ID, /v/ID
_PATH_PATTERNS = (
    re.compile(r"youtu\.be/(?P<id>[a-zA-Z0-9_-]{11})"),
    re.compile(r"youtube\.com/embed/(?P<id>[a-zA-Z0-9_-]{11})"),
    re.compile(r"youtube\.com/shorts/(?P<id>[a-zA-Z0-9_-]{11})"),
    re.compile(r"youtube\.com/v/(?P<id>[a-zA-Z0-9_-]{11})"),
)


@dataclass(frozen=True)
class YouTubeUrlInfo:
    """Parsed result from a YouTube URL."""

    video_id: str
    canonical_url: str


def is_valid_youtube_url(url: str) -> bool:
    """Return True if the string is a recognizable YouTube video URL."""
    try:
        parse_youtube_url(url)
        return True
    except InvalidYouTubeURLError:
        return False


def parse_youtube_url(url: str) -> YouTubeUrlInfo:
    """
    Extract the video ID from a YouTube URL and return a canonical watch URL.

    Supported formats:
        - https://www.youtube.com/watch?v=VIDEO_ID
        - https://youtu.be/VIDEO_ID
        - https://www.youtube.com/embed/VIDEO_ID
        - https://www.youtube.com/shorts/VIDEO_ID
        - https://www.youtube.com/v/VIDEO_ID

    Raises:
        InvalidYouTubeURLError: if the URL is empty, not YouTube, or has no valid ID.
    """
    if not url or not url.strip():
        raise InvalidYouTubeURLError("URL cannot be empty.")

    normalized = url.strip()

    # Ensure urlparse sees a scheme (required for watch URLs with query params).
    if not normalized.startswith(("http://", "https://")):
        normalized = f"https://{normalized}"

    parsed = urlparse(normalized)
    hostname = (parsed.hostname or "").lower().replace("www.", "")

    if hostname not in ("youtube.com", "youtu.be", "m.youtube.com"):
        raise InvalidYouTubeURLError(f"Not a YouTube URL: {url}")

    video_id: str | None = None

    # watch?v=VIDEO_ID (also handles &t=, &list=, etc.)
    if hostname in ("youtube.com", "m.youtube.com") and parsed.path in ("/watch", ""):
        query_ids = parse_qs(parsed.query).get("v", [])
        if query_ids and _VIDEO_ID_PATTERN.match(query_ids[0]):
            video_id = query_ids[0]

    # Path-based patterns (youtu.be, embed, shorts, /v/)
    if video_id is None:
        for pattern in _PATH_PATTERNS:
            match = pattern.search(normalized)
            if match:
                video_id = match.group("id")
                break

    if video_id is None or not _VIDEO_ID_PATTERN.match(video_id):
        raise InvalidYouTubeURLError(f"Could not extract a valid video ID from: {url}")

    canonical_url = f"https://www.youtube.com/watch?v={video_id}"
    return YouTubeUrlInfo(video_id=video_id, canonical_url=canonical_url)
