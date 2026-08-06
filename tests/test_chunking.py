"""Tests for transcript chunking."""

from app.models.transcript import TranscriptSegment
from app.utils.chunking import chunk_transcript


def _segments(texts: list[str]) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    start = 0.0
    for text in texts:
        segments.append(
            TranscriptSegment(
                text=text,
                start_time_sec=start,
                duration_sec=2.0,
            )
        )
        start += 2.0
    return segments


class TestChunkTranscript:
    def test_empty_segments_returns_empty(self) -> None:
        assert chunk_transcript([], chunk_size=100, chunk_overlap=10) == []

    def test_single_short_segment(self) -> None:
        segments = _segments(["Hello world"])
        chunks = chunk_transcript(segments, chunk_size=500, chunk_overlap=50)
        assert len(chunks) == 1
        assert chunks[0].text == "Hello world"
        assert chunks[0].chunk_index == 0
        assert chunks[0].start_time_sec == 0.0
        assert chunks[0].end_time_sec == 2.0

    def test_multiple_chunks_with_overlap(self) -> None:
        long_text = "word " * 120  # ~600 chars
        segments = _segments([long_text.strip(), "tail segment"])
        chunks = chunk_transcript(segments, chunk_size=200, chunk_overlap=30)
        assert len(chunks) >= 2
        assert chunks[0].chunk_index == 0
        assert chunks[1].chunk_index == 1
        assert chunks[0].start_time_sec == 0.0
        assert chunks[-1].end_time_sec == segments[-1].start_time_sec + 2.0

    def test_preserves_timestamps(self) -> None:
        segments = [
            TranscriptSegment(text="first", start_time_sec=1.5, duration_sec=3.0),
            TranscriptSegment(text="second", start_time_sec=4.5, duration_sec=2.5),
        ]
        chunks = chunk_transcript(segments, chunk_size=500, chunk_overlap=0)
        assert len(chunks) == 1
        assert chunks[0].start_time_sec == 1.5
        assert chunks[0].end_time_sec == 7.0
