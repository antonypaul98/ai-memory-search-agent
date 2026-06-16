"""Tests for YouTube transcript fetching."""

from unittest.mock import MagicMock

import pytest

from app.core.exceptions import (
    InvalidYouTubeURLError,
    TranscriptFetchError,
    TranscriptUnavailableError,
)
from app.services.transcript_service import TranscriptService


def _make_snippet(text: str, start: float, duration: float) -> MagicMock:
    snippet = MagicMock()
    snippet.text = text
    snippet.start = start
    snippet.duration = duration
    return snippet


def _make_fetched(*, language_code: str = "en", is_generated: bool = False) -> MagicMock:
    fetched = MagicMock()
    fetched.language_code = language_code
    fetched.is_generated = is_generated
    fetched.snippets = [
        _make_snippet("Hello world.", 0.0, 2.5),
        _make_snippet("Second line.", 2.5, 3.0),
    ]
    return fetched


class TestTranscriptService:
    def test_invalid_url_raises(self) -> None:
        service = TranscriptService(api=MagicMock())
        with pytest.raises(InvalidYouTubeURLError):
            service.fetch_transcript("https://example.com/not-youtube")

    def test_fetch_transcript_success(self) -> None:
        mock_api = MagicMock()
        mock_transcript = MagicMock()
        mock_transcript.fetch.return_value = _make_fetched(is_generated=False)

        mock_transcript_list = MagicMock()
        mock_transcript_list.__iter__ = MagicMock(
            return_value=iter([MagicMock(language_code="en")])
        )
        mock_transcript_list.find_manually_created_transcript.return_value = (
            mock_transcript
        )
        mock_api.list.return_value = mock_transcript_list

        service = TranscriptService(api=mock_api)
        result = service.fetch_transcript(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )

        assert result.video_id == "dQw4w9WgXcQ"
        assert result.language == "en"
        assert result.is_generated is False
        assert len(result.segments) == 2
        assert result.full_text == "Hello world. Second line."

    def test_no_transcript_raises_unavailable(self) -> None:
        from youtube_transcript_api._errors import TranscriptsDisabled

        mock_api = MagicMock()
        mock_api.list.side_effect = TranscriptsDisabled("dQw4w9WgXcQ")

        service = TranscriptService(api=mock_api)
        with pytest.raises(TranscriptUnavailableError):
            service.fetch_transcript(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
            )

    def test_network_error_raises_fetch_error(self) -> None:
        from youtube_transcript_api._errors import YouTubeRequestFailed

        mock_api = MagicMock()
        mock_api.list.side_effect = YouTubeRequestFailed(
            "dQw4w9WgXcQ",
            Exception("network timeout"),
        )

        service = TranscriptService(api=mock_api)
        with pytest.raises(TranscriptFetchError):
            service.fetch_transcript(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
            )
