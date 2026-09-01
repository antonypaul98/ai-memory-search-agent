"""YouTube-specific duplicate detection built on shared hash utilities."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings
from app.db.youtube_memory_store_factory import get_youtube_memory_store
from app.models.youtube_memory import YouTubeMemory
from app.services.deduplication_service import hash_text, hamming_distance, simhash64
from app.utils.url_parser import parse_youtube_url
from app.core.exceptions import InvalidYouTubeURLError


@dataclass
class DuplicateReport:
    is_duplicate: bool
    reason: str = ""
    duplicate_of: str | None = None
    match_type: str = ""  # exact_video_id | content_hash | near_title | none


class YouTubeDuplicateDetector:
    def __init__(self, store=None, settings: Settings | None = None) -> None:
        self._store = store if store is not None else get_youtube_memory_store(settings or get_settings())

    def check_url(self, url: str, *, user_id: str) -> DuplicateReport:
        try:
            video_id = parse_youtube_url(url).video_id
        except InvalidYouTubeURLError:
            return DuplicateReport(is_duplicate=False, match_type="none")
        existing = self._store.get(video_id, user_id=user_id)
        if existing and existing.processing_status.value in {"completed", "indexed"}:
            return DuplicateReport(
                is_duplicate=True,
                reason="Video already in Memory",
                duplicate_of=existing.video_id,
                match_type="exact_video_id",
            )
        return DuplicateReport(is_duplicate=False, match_type="none")

    def check_memory(self, memory: YouTubeMemory, *, user_id: str) -> DuplicateReport:
        by_id = self._store.get(memory.video_id, user_id=user_id)
        if by_id and by_id.memory_id != memory.memory_id:
            if by_id.processing_status.value in {"completed", "indexed"}:
                return DuplicateReport(
                    is_duplicate=True,
                    reason="Same video ID already saved",
                    duplicate_of=by_id.video_id,
                    match_type="exact_video_id",
                )
        if memory.content_hash:
            by_hash = self._store.get_by_content_hash(memory.content_hash, user_id=user_id)
            if by_hash and by_hash.video_id != memory.video_id:
                return DuplicateReport(
                    is_duplicate=True,
                    reason="Same content hash (possible re-upload)",
                    duplicate_of=by_hash.video_id,
                    match_type="content_hash",
                )
        # Near-duplicate titles from same channel
        peers = self._store.list_for_user(user_id, limit=100)
        mem_hash = simhash64(f"{memory.channel}|{memory.title}")
        for peer in peers:
            if peer.video_id == memory.video_id:
                continue
            if peer.channel.lower() != memory.channel.lower():
                continue
            if hamming_distance(mem_hash, simhash64(f"{peer.channel}|{peer.title}")) <= 3:
                return DuplicateReport(
                    is_duplicate=True,
                    reason="Near-duplicate title from same channel",
                    duplicate_of=peer.video_id,
                    match_type="near_title",
                )
        return DuplicateReport(is_duplicate=False, match_type="none")

    @staticmethod
    def same_video_different_url(url_a: str, url_b: str) -> bool:
        try:
            return parse_youtube_url(url_a).video_id == parse_youtube_url(url_b).video_id
        except InvalidYouTubeURLError:
            return False

    @staticmethod
    def url_fingerprint(url: str) -> str:
        try:
            return hash_text(parse_youtube_url(url).video_id)
        except InvalidYouTubeURLError:
            return hash_text(url)
