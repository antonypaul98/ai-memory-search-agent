"""
Split long transcript text into overlapping chunks for embedding.

Each chunk preserves start/end timestamps from the source segments.
"""

from dataclasses import dataclass

from app.models.transcript import TranscriptSegment


@dataclass(frozen=True)
class TranscriptChunk:
    """One embeddable chunk derived from timed transcript segments."""

    chunk_index: int
    text: str
    start_time_sec: float
    end_time_sec: float


def chunk_transcript(
    segments: list[TranscriptSegment],
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[TranscriptChunk]:
    """
    Build overlapping text chunks from timed transcript segments.

    Args:
        segments: Ordered transcript segments with timestamps.
        chunk_size: Target maximum characters per chunk.
        chunk_overlap: Characters to overlap between consecutive chunks.

    Returns:
        Structured chunks ready for embedding and Chroma storage.
    """
    if not segments or chunk_size <= 0:
        return []

    overlap = max(0, min(chunk_overlap, chunk_size - 1))
    chunks: list[TranscriptChunk] = []
    start_idx = 0
    chunk_index = 0

    while start_idx < len(segments):
        parts: list[str] = []
        char_count = 0
        end_idx = start_idx

        while end_idx < len(segments):
            seg_text = segments[end_idx].text.strip()
            if not seg_text:
                end_idx += 1
                continue

            separator = 1 if parts else 0
            addition = len(seg_text) + separator

            if parts and char_count + addition > chunk_size:
                break

            parts.append(seg_text)
            char_count += addition
            end_idx += 1

            if char_count >= chunk_size:
                break

        if not parts:
            break

        text = " ".join(parts)
        start_time = segments[start_idx].start_time_sec
        last_seg = segments[end_idx - 1]
        end_time = last_seg.start_time_sec + last_seg.duration_sec

        chunks.append(
            TranscriptChunk(
                chunk_index=chunk_index,
                text=text,
                start_time_sec=start_time,
                end_time_sec=end_time,
            )
        )
        chunk_index += 1

        if end_idx >= len(segments):
            break

        next_start = end_idx
        overlap_chars = 0
        while next_start > start_idx and overlap_chars < overlap:
            next_start -= 1
            overlap_chars += len(segments[next_start].text.strip()) + 1

        if next_start <= start_idx:
            start_idx = end_idx
        else:
            start_idx = next_start

    return chunks
