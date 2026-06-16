"""
Fetch YouTube video transcripts.

Phase 2: fetch only — no chunking, embedding, or Chroma writes.
Called by tests and (Phase 3+) IngestService.
"""

import re
from typing import TYPE_CHECKING

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeRequestFailed,
)

from app.core.exceptions import (
    TranscriptFetchError,
    TranscriptUnavailableError,
)
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.utils.url_parser import parse_youtube_url

if TYPE_CHECKING:
    from youtube_transcript_api._transcripts import FetchedTranscript


class TranscriptService:
    """Fetch and normalize YouTube transcripts for a given video URL."""

    def __init__(self, api: YouTubeTranscriptApi | None = None) -> None:
        # Inject api in tests; production code uses a real client instance.
        self._api = api or YouTubeTranscriptApi()

    def fetch_transcript(self, url: str) -> TranscriptResult:
        """
        Fetch the transcript for a YouTube video.

        Args:
            url: Any supported YouTube URL format.

        Returns:
            TranscriptResult with timed segments and joined full_text.

        Raises:
            InvalidYouTubeURLError: bad URL (from url_parser).
            TranscriptUnavailableError: no captions or video unavailable.
            TranscriptFetchError: network or YouTube API failure.
        """
        url_info = parse_youtube_url(url)
        video_id = url_info.video_id

        try:
            fetched = self._fetch_with_manual_preference(video_id)
        except (TranscriptsDisabled, NoTranscriptFound) as exc:
            raise TranscriptUnavailableError(
                f"No transcript available for video {video_id}."
            ) from exc
        except VideoUnavailable as exc:
            raise TranscriptUnavailableError(
                f"Video {video_id} is unavailable or private."
            ) from exc
        except YouTubeRequestFailed as exc:
            raise TranscriptFetchError(
                f"Failed to fetch transcript for {video_id}: {exc}"
            ) from exc
        except Exception as exc:
            raise TranscriptFetchError(
                f"Unexpected error fetching transcript for {video_id}: {exc}"
            ) from exc

        segments = [
            TranscriptSegment(
                text=snippet.text,
                start_time_sec=float(snippet.start),
                duration_sec=float(snippet.duration),
            )
            for snippet in fetched.snippets
        ]

        full_text = _normalize_text(" ".join(seg.text for seg in segments))

        return TranscriptResult(
            video_id=video_id,
            canonical_url=url_info.canonical_url,
            segments=segments,
            full_text=full_text,
            language=fetched.language_code,
            is_generated=fetched.is_generated,
        )

    def _fetch_with_manual_preference(self, video_id: str) -> "FetchedTranscript":
        """
        Prefer manually uploaded captions; fall back to auto-generated.

        Uses the instance-based youtube-transcript-api (list → find → fetch).
        """
        transcript_list = self._api.list(video_id)
        language_codes = [t.language_code for t in transcript_list]

        try:
            transcript = transcript_list.find_manually_created_transcript(
                language_codes
            )
        except NoTranscriptFound:
            transcript = transcript_list.find_generated_transcript(language_codes)

        return transcript.fetch()


def _normalize_text(text: str) -> str:
    """Collapse repeated whitespace and strip leading/trailing space."""
    return re.sub(r"\s+", " ", text).strip()
