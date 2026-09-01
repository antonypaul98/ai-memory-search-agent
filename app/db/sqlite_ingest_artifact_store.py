"""SQLite compatibility store for ingest artifacts.

This adapter preserves the historical local/self-host storage shape while exposing
one tenant-explicit interface shared with Postgres. The legacy SQLite tables are
not tenant-keyed, so callers must still pass user identity even though SQLite
cannot enforce tenant isolation internally. Production multi-tenant cutover is
therefore gated on the Postgres backend and migration acceptance work.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import Settings
from app.db.schema import get_connection, migrate


class SQLiteIngestArtifactStore:
    """Compatibility implementation over legacy SQLite ingest-artifact tables."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        migrate(settings)

    def transcript_unchanged(self, *, user_id: str, video_id: str, transcript_hash: str) -> bool:
        _required("user_id", user_id)
        video_id = _required("video_id", video_id)
        transcript_hash = _required("transcript_hash", transcript_hash)
        with get_connection(self._settings) as conn:
            row = conn.execute(
                "SELECT transcript_hash FROM content_hashes WHERE video_id = ?",
                (video_id,),
            ).fetchone()
        return bool(row and row["transcript_hash"] == transcript_hash)

    def store_transcript_hash(self, *, user_id: str, video_id: str, transcript_hash: str) -> None:
        _required("user_id", user_id)
        video_id = _required("video_id", video_id)
        transcript_hash = _required("transcript_hash", transcript_hash)
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO content_hashes (
                    video_id, transcript_hash, normalized_path, updated_at
                ) VALUES (?, ?, ?, ?)
                """,
                (video_id, transcript_hash, "", datetime.now(timezone.utc).isoformat()),
            )

    def store_capsule_json(self, *, user_id: str, video_id: str, capsule_json: str) -> None:
        _required("user_id", user_id)
        video_id = _required("video_id", video_id)
        capsule_json = _required("capsule_json", capsule_json)
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO memory_capsules_json (video_id, capsule_json, updated_at)
                VALUES (?, ?, ?)
                """,
                (video_id, capsule_json, datetime.now(timezone.utc).isoformat()),
            )


def _required(name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized
