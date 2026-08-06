"""Tests for chat service source handling."""

from app.services.chat_service import _dedupe_sources, _to_chat_source


class TestChatServiceHelpers:
    def test_dedupe_sources_same_timestamp_bucket(self) -> None:
        chunks = [
            {
                "video_id": "vid1",
                "title": "GPU Setup",
                "url": "https://www.youtube.com/watch?v=vid1",
                "start_time": 10.0,
                "end_time": 20.0,
                "matched_text": "lower score",
                "relevance_score": 0.5,
            },
            {
                "video_id": "vid1",
                "title": "GPU Setup",
                "url": "https://www.youtube.com/watch?v=vid1",
                "start_time": 12.0,
                "end_time": 25.0,
                "matched_text": "higher score",
                "relevance_score": 0.9,
            },
        ]
        deduped = _dedupe_sources(chunks)
        assert len(deduped) == 1
        assert deduped[0]["matched_text"] == "higher score"

    def test_to_chat_source_builds_timestamp_url(self) -> None:
        source = _to_chat_source(
            {
                "video_id": "dQw4w9WgXcQ",
                "title": "Demo",
                "url": "https://youtu.be/dQw4w9WgXcQ",
                "start_time": 762.0,
                "end_time": 810.0,
                "matched_text": "install the gpu driver",
                "relevance_score": 0.82,
            }
        )
        assert source.url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert source.timestamp_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=762"
        assert source.relevance_score == 0.82
