"""Durable, tenant-scoped spaced-review metadata for the Review Agent."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import Settings, get_settings
from app.db.schema import get_connection
from app.db.video_registry import get_video_registry

_OUTCOME_INTERVAL_DAYS = {
    "again": 1,
    "hard": 3,
    "good": 7,
    "easy": 14,
}


class ReviewScheduleService:
    """Record review outcomes and compute the next deterministic review date.

    This store contains review metadata only. It never edits source content,
    embeddings, provenance, or graph relationships.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._ensure_table()

    def _ensure_table(self) -> None:
        with get_connection(self._settings) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_review_schedule (
                    user_id TEXT NOT NULL,
                    video_id TEXT NOT NULL,
                    last_reviewed_at TEXT NOT NULL,
                    next_review_at TEXT NOT NULL,
                    review_count INTEGER NOT NULL DEFAULT 0,
                    last_result TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, video_id)
                );
                CREATE INDEX IF NOT EXISTS idx_memory_review_due
                    ON memory_review_schedule(user_id, next_review_at);
                """
            )

    def record_result(
        self,
        *,
        user_id: str,
        video_id: str,
        result: str,
        reviewed_at: datetime | None = None,
    ) -> dict[str, object]:
        user_id = (user_id or "").strip()
        video_id = (video_id or "").strip()
        outcome = (result or "").strip().casefold()
        if not user_id or not video_id:
            raise ValueError("user_id and video_id are required")
        if outcome not in _OUTCOME_INTERVAL_DAYS:
            raise ValueError("review result must be one of: again, hard, good, easy")

        registry = get_video_registry(self._settings)
        if not registry.get_video(video_id, user_id=user_id):
            raise KeyError("video not found")

        reviewed = reviewed_at or datetime.now(timezone.utc)
        if reviewed.tzinfo is None:
            reviewed = reviewed.replace(tzinfo=timezone.utc)
        reviewed = reviewed.astimezone(timezone.utc)
        next_review = reviewed + timedelta(days=_OUTCOME_INTERVAL_DAYS[outcome])
        reviewed_iso = reviewed.isoformat()
        next_iso = next_review.isoformat()

        with get_connection(self._settings) as conn:
            existing = conn.execute(
                "SELECT review_count FROM memory_review_schedule WHERE user_id = ? AND video_id = ?",
                (user_id, video_id),
            ).fetchone()
            count = (int(existing["review_count"]) if existing else 0) + 1
            conn.execute(
                """
                INSERT INTO memory_review_schedule (
                    user_id, video_id, last_reviewed_at, next_review_at,
                    review_count, last_result, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, video_id) DO UPDATE SET
                    last_reviewed_at = excluded.last_reviewed_at,
                    next_review_at = excluded.next_review_at,
                    review_count = excluded.review_count,
                    last_result = excluded.last_result,
                    updated_at = excluded.updated_at
                """,
                (user_id, video_id, reviewed_iso, next_iso, count, outcome, reviewed_iso),
            )

        return {
            "video_id": video_id,
            "result": outcome,
            "review_count": count,
            "last_reviewed_at": reviewed_iso,
            "next_review_at": next_iso,
        }

    def get(self, *, user_id: str, video_id: str) -> dict[str, object] | None:
        with get_connection(self._settings) as conn:
            row = conn.execute(
                """
                SELECT user_id, video_id, last_reviewed_at, next_review_at,
                       review_count, last_result
                FROM memory_review_schedule
                WHERE user_id = ? AND video_id = ?
                """,
                (user_id, video_id),
            ).fetchone()
        return dict(row) if row else None
