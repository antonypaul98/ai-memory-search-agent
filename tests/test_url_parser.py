"""Tests for YouTube URL parsing."""

import pytest

from app.core.exceptions import InvalidYouTubeURLError
from app.utils.url_parser import is_valid_youtube_url, parse_youtube_url


class TestParseYoutubeUrl:
    def test_standard_watch_url(self) -> None:
        info = parse_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert info.video_id == "dQw4w9WgXcQ"
        assert info.canonical_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_watch_url_with_extra_params(self) -> None:
        info = parse_youtube_url(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&list=PLtest"
        )
        assert info.video_id == "dQw4w9WgXcQ"

    def test_short_youtu_be_url(self) -> None:
        info = parse_youtube_url("https://youtu.be/dQw4w9WgXcQ")
        assert info.video_id == "dQw4w9WgXcQ"

    def test_embed_url(self) -> None:
        info = parse_youtube_url("https://www.youtube.com/embed/dQw4w9WgXcQ")
        assert info.video_id == "dQw4w9WgXcQ"

    def test_shorts_url(self) -> None:
        info = parse_youtube_url("https://www.youtube.com/shorts/dQw4w9WgXcQ")
        assert info.video_id == "dQw4w9WgXcQ"

    def test_url_without_scheme(self) -> None:
        info = parse_youtube_url("www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert info.video_id == "dQw4w9WgXcQ"

    def test_empty_url_raises(self) -> None:
        with pytest.raises(InvalidYouTubeURLError):
            parse_youtube_url("")

    def test_non_youtube_url_raises(self) -> None:
        with pytest.raises(InvalidYouTubeURLError):
            parse_youtube_url("https://example.com/watch?v=dQw4w9WgXcQ")

    def test_youtube_url_without_video_id_raises(self) -> None:
        with pytest.raises(InvalidYouTubeURLError):
            parse_youtube_url("https://www.youtube.com/watch")


class TestIsValidYoutubeUrl:
    def test_valid_url(self) -> None:
        assert is_valid_youtube_url("https://youtu.be/dQw4w9WgXcQ") is True

    def test_invalid_url(self) -> None:
        assert is_valid_youtube_url("not-a-url") is False
