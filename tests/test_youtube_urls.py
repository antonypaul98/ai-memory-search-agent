"""Tests for YouTube timestamp URL construction."""

from app.utils.youtube_urls import build_original_url, build_timestamp_url


class TestBuildTimestampUrl:
    def test_watch_url(self) -> None:
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert (
            build_timestamp_url(url, 42.7)
            == "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42"
        )

    def test_watch_url_with_existing_params(self) -> None:
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLtest"
        result = build_timestamp_url(url, 90.0)
        assert result.startswith("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert "t=90" in result

    def test_youtu_be_url(self) -> None:
        url = "https://youtu.be/dQw4w9WgXcQ"
        assert (
            build_timestamp_url(url, 15.0)
            == "https://youtu.be/dQw4w9WgXcQ?t=15"
        )

    def test_shorts_url(self) -> None:
        url = "https://www.youtube.com/shorts/dQw4w9WgXcQ"
        assert (
            build_timestamp_url(url, 5.0)
            == "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=5"
        )

    def test_none_start_time_returns_original(self) -> None:
        url = "https://youtu.be/dQw4w9WgXcQ"
        assert build_timestamp_url(url, None) == url


class TestBuildOriginalUrl:
    def test_normalizes_youtu_be(self) -> None:
        assert (
            build_original_url("https://youtu.be/dQw4w9WgXcQ")
            == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )
