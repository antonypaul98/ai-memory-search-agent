"""
YouTube URL helpers for timestamp links.
"""

from urllib.parse import parse_qs, urlparse

from app.utils.url_parser import parse_youtube_url


def build_timestamp_url(url: str, start_time: float | None) -> str:
    """
    Build a clickable YouTube URL that jumps to start_time.

    Supports youtube.com/watch, youtu.be, /shorts, and other formats
    handled by parse_youtube_url.
    """
    if start_time is None:
        return url

    seconds = max(0, int(start_time))
    if not url.strip():
        return url

    try:
        info = parse_youtube_url(url)
    except Exception:
        # Fall back to simple query append if parsing fails.
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}t={seconds}"

    canonical = info.canonical_url
    parsed = urlparse(url.strip())
    hostname = (parsed.hostname or "").lower().replace("www.", "")

    if hostname == "youtu.be":
        base = f"https://youtu.be/{info.video_id}"
        return f"{base}?t={seconds}"

    return f"{canonical}&t={seconds}" if "?" in canonical else f"{canonical}?t={seconds}"


def build_original_url(url: str) -> str:
    """Normalize any supported YouTube URL to a canonical watch URL."""
    try:
        return parse_youtube_url(url).canonical_url
    except Exception:
        return url
