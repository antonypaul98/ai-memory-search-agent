"""Python mirror tests for extension Context Observer helpers."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse


RESTRICTED_PREFIXES = (
    "chrome://",
    "chrome-extension://",
    "edge://",
    "about:",
    "devtools://",
    "view-source:",
    "chrome-search://",
    "chrome-devtools://",
)


def is_restricted_url(url: str | None) -> bool:
    if not url:
        return True
    lower = url.lower()
    return any(lower.startswith(p) for p in RESTRICTED_PREFIXES)


def classify_platform(url: str) -> str:
    if is_restricted_url(url):
        return "unsupported"
    try:
        parsed = urlparse(url)
        host = parsed.hostname.replace("www.", "") if parsed.hostname else ""
        if host in {"youtube.com", "m.youtube.com", "youtu.be"}:
            return "youtube"
        if parsed.scheme in {"http", "https"}:
            return "web"
    except Exception:
        return "unsupported"
    return "unsupported"


def extract_youtube_video_id(url: str) -> str | None:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").replace("www.", "")
        if "youtu.be" in host:
            parts = [p for p in parsed.path.split("/") if p]
            return parts[0] if parts else None
        qs = parse_qs(parsed.query)
        if qs.get("v"):
            return qs["v"][0]
        m = re.search(r"/(?:shorts|embed|live)/([^/?]+)", parsed.path)
        if m:
            return m.group(1)
    except Exception:
        return None
    return None


class TestExtensionContextHelpers:
    def test_restricted_urls(self) -> None:
        assert is_restricted_url("chrome://settings")
        assert is_restricted_url("about:blank")
        assert not is_restricted_url("https://www.youtube.com/watch?v=abc")

    def test_classify(self) -> None:
        assert classify_platform("https://www.youtube.com/watch?v=abc123") == "youtube"
        assert classify_platform("https://youtu.be/abc123") == "youtube"
        assert classify_platform("https://example.com/article") == "web"

    def test_video_id(self) -> None:
        assert (
            extract_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            == "dQw4w9WgXcQ"
        )
        assert extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
