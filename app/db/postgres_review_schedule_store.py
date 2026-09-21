"""Tenant-scoped review metadata, selected with the canonical memory backend."""

from __future__ import annotations

from app.db.account_erasure_fence import require_active_tenant

from app.db.postgres_job_repository import ConnectionFactory


class PostgresReviewScheduleStore:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory
        with connection_factory() as conn:
            conn.execute(
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
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_review_due "
                "ON memory_review_schedule(user_id, next_review_at)"
            )

    def record_result(
        self, *, user_id: str, video_id: str, outcome: str,
        reviewed_iso: str, next_iso: str,
    ) -> int:
        # Increment inside the upsert: a read-then-write count loses concurrent
        # reviews. RETURNING reports the count belonging to this transaction.
        with self._connection_factory() as conn:
            require_active_tenant(conn, user_id=user_id)
            row = conn.execute(
                """
                INSERT INTO memory_review_schedule (
                    user_id, video_id, last_reviewed_at, next_review_at,
                    review_count, last_result, updated_at
                ) VALUES (%s, %s, %s, %s, 1, %s, %s)
                ON CONFLICT(user_id, video_id) DO UPDATE SET
                    last_reviewed_at = EXCLUDED.last_reviewed_at,
                    next_review_at = EXCLUDED.next_review_at,
                    review_count = memory_review_schedule.review_count + 1,
                    last_result = EXCLUDED.last_result,
                    updated_at = EXCLUDED.updated_at
                RETURNING review_count
                """,
                (user_id, video_id, reviewed_iso, next_iso, outcome, reviewed_iso),
            ).fetchone()
        return int(row["review_count"])

    def get(self, *, user_id: str, video_id: str) -> dict[str, object] | None:
        with self._connection_factory() as conn:
            row = conn.execute(
                """
                SELECT user_id, video_id, last_reviewed_at, next_review_at,
                       review_count, last_result
                FROM memory_review_schedule
                WHERE user_id = %s AND video_id = %s
                """,
                (user_id, video_id),
            ).fetchone()
        return dict(row) if row else None

    def list_for_user(self, *, user_id: str) -> list[dict[str, object]]:
        with self._connection_factory() as conn:
            rows = conn.execute(
                "SELECT user_id, video_id, last_reviewed_at, next_review_at, "
                "review_count, last_result FROM memory_review_schedule "
                "WHERE user_id = %s ORDER BY video_id",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete(self, *, user_id: str, video_id: str) -> int:
        with self._connection_factory() as conn:
            cursor = conn.execute(
                "DELETE FROM memory_review_schedule WHERE user_id = %s AND video_id = %s",
                (user_id, video_id),
            )
        return int(cursor.rowcount)
