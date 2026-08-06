"""
Fetch transcripts via the connector registry (YouTubeConnector for YouTube URLs).

Keeps a stable TranscriptService API for IngestService and tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.exceptions import TranscriptUnavailableError
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.services.sources import get_connector_registry
from app.services.sources.base_source import TranscriptKind

if TYPE_CHECKING:
    from youtube_transcript_api import YouTubeTranscriptApi


class TranscriptService:
    """Fetch and normalize transcripts for a given URL via SourceConnector."""

    def __init__(self, api: YouTubeTranscriptApi | None = None) -> None:
        # Kept for test injection compatibility; YouTubeConnector owns the real client.
        self._api = api

    def fetch_transcript(self, url: str) -> TranscriptResult:
        from app.core.exceptions import AppError, InvalidYouTubeURLError
        from app.utils.url_parser import is_valid_youtube_url

        # Legacy TranscriptService remains YouTube-scoped; other sources use ConnectorIngestService.
        if not is_valid_youtube_url(url):
            raise InvalidYouTubeURLError("URL is not a valid YouTube link.")

        try:
            connector = get_connector_registry().get("youtube.v1")
        except AppError as exc:
            raise InvalidYouTubeURLError(str(exc)) from exc
        ref = connector.parse_ref(url)
        if self._api is not None:
            return self._fetch_with_injected_api(ref.external_id, ref.url)

        payload = connector.fetch_transcript(ref)
        if not payload.segments and not payload.full_text:
            raise TranscriptUnavailableError(
                f"No transcript available for video {ref.external_id}."
            )
        return TranscriptResult(
            video_id=payload.external_id,
            canonical_url=ref.url,
            segments=[
                TranscriptSegment(
                    text=s.text,
                    start_time_sec=s.start_time_sec,
                    duration_sec=s.duration_sec,
                )
                for s in payload.segments
            ],
            full_text=payload.full_text,
            language=payload.language,
            is_generated=payload.kind == TranscriptKind.AUTO_GENERATED,
        )

    def detect_availability(self, url: str):
        from app.core.exceptions import InvalidYouTubeURLError
        from app.utils.url_parser import is_valid_youtube_url

        if not is_valid_youtube_url(url):
            raise InvalidYouTubeURLError("URL is not a valid YouTube link.")
        connector = get_connector_registry().get("youtube.v1")
        ref = connector.parse_ref(url)
        return connector.detect_transcript(ref)

    def _fetch_with_injected_api(self, video_id: str, canonical_url: str) -> TranscriptResult:
        """Unit-test path matching previous TranscriptService behavior."""
        import re

        from youtube_transcript_api._errors import (
            NoTranscriptFound,
            TranscriptsDisabled,
            VideoUnavailable,
            YouTubeRequestFailed,
        )

        from app.core.exceptions import TranscriptFetchError, TranscriptUnavailableError

        assert self._api is not None
        try:
            transcript_list = self._api.list(video_id)
            language_codes = [t.language_code for t in transcript_list]
            try:
                transcript = transcript_list.find_manually_created_transcript(language_codes)
                is_generated = False
            except NoTranscriptFound:
                transcript = transcript_list.find_generated_transcript(language_codes)
                is_generated = True
            fetched = transcript.fetch()
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

        segments = [
            TranscriptSegment(
                text=snippet.text,
                start_time_sec=float(snippet.start),
                duration_sec=float(snippet.duration),
            )
            for snippet in fetched.snippets
        ]
        full_text = re.sub(r"\s+", " ", " ".join(seg.text for seg in segments)).strip()
        return TranscriptResult(
            video_id=video_id,
            canonical_url=canonical_url,
            segments=segments,
            full_text=full_text,
            language=fetched.language_code,
            is_generated=is_generated,
        )
