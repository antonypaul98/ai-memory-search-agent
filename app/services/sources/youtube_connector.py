"""YouTube connector — the only module that talks to yt-dlp / youtube-transcript-api."""

from __future__ import annotations

import re
from typing import Any

from app.core.exceptions import (
    InvalidYouTubeURLError,
    MetadataFetchError,
    TranscriptFetchError,
    TranscriptUnavailableError,
)
from app.models.video import SourceType
from app.services.deduplication_service import hash_text
from app.services.sources.base_source import (
    ConnectorHealth,
    NormalizedItem,
    SourceConnector,
    SourceRef,
    TextSegment,
    TranscriptAvailability,
    TranscriptKind,
    TranscriptPayload,
)
from app.utils.url_parser import parse_youtube_url

CONNECTOR_ID = "youtube.v1"


class YouTubeConnector(SourceConnector):
    """Production YouTube connector used as the reference for future connectors."""

    source_type = SourceType.YOUTUBE
    connector_id = CONNECTOR_ID

    def health(self) -> ConnectorHealth:
        try:
            import yt_dlp  # noqa: F401
            from youtube_transcript_api import YouTubeTranscriptApi  # noqa: F401

            return ConnectorHealth(connector_id=self.connector_id, healthy=True, detail="ok")
        except Exception as exc:
            return ConnectorHealth(
                connector_id=self.connector_id,
                healthy=False,
                detail=str(exc),
            )

    def parse_ref(self, url: str) -> SourceRef:
        info = parse_youtube_url(url)
        return SourceRef(url=info.canonical_url, external_id=info.video_id)

    def fetch_metadata(self, ref: SourceRef) -> NormalizedItem:
        import yt_dlp

        if not ref.external_id:
            ref = self.parse_ref(ref.url)

        ydl_opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": False,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(ref.url, download=False)
        except Exception as exc:
            raise MetadataFetchError(
                f"Failed to fetch metadata for {ref.external_id}: {exc}"
            ) from exc

        if not info:
            raise MetadataFetchError(f"No metadata returned for video {ref.external_id}.")

        video_id = str(info.get("id") or ref.external_id)
        thumbnail = info.get("thumbnail") or ""
        if not thumbnail:
            thumbs = info.get("thumbnails") or []
            if thumbs:
                thumbnail = thumbs[-1].get("url", "") or ""

        duration = info.get("duration")
        duration_sec = float(duration) if duration is not None else None

        published = _normalize_upload_date(info.get("upload_date") or info.get("release_date"))
        channel_id = str(info.get("channel_id") or info.get("uploader_id") or "")
        channel = str(info.get("uploader") or info.get("channel") or "Unknown")
        title = str(info.get("title") or "Untitled").strip() or "Untitled"
        description = str(info.get("description") or "")
        tags = [str(t) for t in (info.get("tags") or []) if t][:50]
        categories = [str(c) for c in (info.get("categories") or []) if c][:20]
        language = info.get("language") or info.get("original_language")
        if language is not None:
            language = str(language)

        playlist_id = ref.extra.get("playlist_id") or info.get("playlist_id")
        playlist_title = ref.extra.get("playlist_title") or info.get("playlist_title")
        playlist_index = ref.extra.get("playlist_index")
        if playlist_index is None and info.get("playlist_index") is not None:
            playlist_index = info.get("playlist_index")

        canonical = str(info.get("webpage_url") or ref.url)
        content_hash = hash_text(f"{video_id}|{title}|{description[:2000]}|{duration_sec}")

        return NormalizedItem(
            source_type=SourceType.YOUTUBE,
            connector_id=self.connector_id,
            external_id=video_id,
            canonical_url=canonical,
            title=title,
            author=channel,
            published_at=published,
            duration_sec=duration_sec,
            language=language,
            thumbnail=thumbnail,
            description=description,
            tags=tags,
            categories=categories,
            content_hash=content_hash,
            raw_metadata={
                "channel_id": channel_id,
                "channel": channel,
                "view_count": info.get("view_count"),
                "like_count": info.get("like_count"),
                "playlist_id": playlist_id,
                "playlist_title": playlist_title,
                "playlist_index": playlist_index,
                "availability": info.get("availability"),
                "live_status": info.get("live_status"),
            },
        )

    def detect_transcript(self, ref: SourceRef) -> TranscriptAvailability:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import (
            NoTranscriptFound,
            TranscriptsDisabled,
            VideoUnavailable,
            YouTubeRequestFailed,
        )

        if not ref.external_id:
            ref = self.parse_ref(ref.url)
        api = YouTubeTranscriptApi()
        try:
            listing = list(api.list(ref.external_id))
            if not listing:
                return TranscriptAvailability.UNAVAILABLE
            return TranscriptAvailability.AVAILABLE
        except TranscriptsDisabled:
            return TranscriptAvailability.DISABLED
        except (NoTranscriptFound, VideoUnavailable):
            return TranscriptAvailability.UNAVAILABLE
        except YouTubeRequestFailed:
            return TranscriptAvailability.UNKNOWN
        except Exception:
            return TranscriptAvailability.UNKNOWN

    def fetch_transcript(self, ref: SourceRef) -> TranscriptPayload:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import (
            NoTranscriptFound,
            TranscriptsDisabled,
            VideoUnavailable,
            YouTubeRequestFailed,
        )

        if not ref.external_id:
            ref = self.parse_ref(ref.url)
        video_id = ref.external_id
        api = YouTubeTranscriptApi()

        try:
            transcript_list = api.list(video_id)
            language_codes = [t.language_code for t in transcript_list]
            kind = TranscriptKind.UNKNOWN
            try:
                transcript = transcript_list.find_manually_created_transcript(language_codes)
                kind = TranscriptKind.MANUAL
            except NoTranscriptFound:
                transcript = transcript_list.find_generated_transcript(language_codes)
                kind = TranscriptKind.AUTO_GENERATED
            fetched = transcript.fetch()
        except (TranscriptsDisabled,) as exc:
            raise TranscriptUnavailableError(
                f"Transcripts disabled for video {video_id}."
            ) from exc
        except (NoTranscriptFound, VideoUnavailable) as exc:
            raise TranscriptUnavailableError(
                f"No transcript available for video {video_id}."
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
            TextSegment(
                text=snippet.text,
                start_time_sec=float(snippet.start),
                duration_sec=float(snippet.duration),
            )
            for snippet in fetched.snippets
        ]
        full_text = re.sub(r"\s+", " ", " ".join(s.text for s in segments)).strip()
        return TranscriptPayload(
            external_id=video_id,
            segments=segments,
            full_text=full_text,
            language=getattr(fetched, "language_code", None),
            kind=kind,
            availability=TranscriptAvailability.AVAILABLE,
        )


def _normalize_upload_date(value: Any) -> str | None:
    if not value:
        return None
    raw = str(value).strip()
    if re.fullmatch(r"\d{8}", raw):
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw
