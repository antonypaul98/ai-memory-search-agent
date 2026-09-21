"""Postgres persistence primitives for tenant-scoped answer feedback."""
from __future__ import annotations

from app.db.account_erasure_fence import require_active_tenant

from datetime import datetime, timezone

from app.db.postgres_job_repository import ConnectionFactory


class PostgresFeedbackStore:
    """Persist feedback, rewards, and learned output preferences without SQLite."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory
        with connection_factory() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS answer_interactions (
                    interaction_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    route_id TEXT NOT NULL DEFAULT '',
                    output_budget_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    route_fingerprint TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_answer_interactions_user_time "
                "ON answer_interactions(user_id, created_at DESC)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS answer_feedback (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    interaction_id TEXT NOT NULL,
                    rating INTEGER NOT NULL,
                    issues_json TEXT NOT NULL DEFAULT '[]',
                    expected_answer_description TEXT NOT NULL DEFAULT '',
                    comment TEXT NOT NULL DEFAULT '',
                    survey_id TEXT,
                    survey_answers_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, interaction_id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_answer_feedback_user_time "
                "ON answer_feedback(user_id, created_at DESC)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback_credit_ledger (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    interaction_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    credits INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, interaction_id, reason)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_feedback_credits_user_time "
                "ON feedback_credit_ledger(user_id, created_at DESC)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS output_preferences (
                    user_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    target_output_tokens INTEGER NOT NULL,
                    sample_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, task_type)
                )
                """
            )

    def record_interaction(
        self,
        *,
        interaction_id: str,
        user_id: str,
        task_type: str,
        route_id: str,
        output_budget_tokens: int,
        completion_tokens: int,
        route_fingerprint: str,
    ) -> None:
        with self._connection_factory() as conn:
            require_active_tenant(conn, user_id=user_id)
            conn.execute(
                """
                INSERT INTO answer_interactions(
                    interaction_id, user_id, task_type, route_id,
                    output_budget_tokens, completion_tokens, route_fingerprint, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(interaction_id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    task_type = EXCLUDED.task_type,
                    route_id = EXCLUDED.route_id,
                    output_budget_tokens = EXCLUDED.output_budget_tokens,
                    completion_tokens = EXCLUDED.completion_tokens,
                    route_fingerprint = EXCLUDED.route_fingerprint,
                    created_at = EXCLUDED.created_at
                """,
                (
                    interaction_id,
                    user_id,
                    task_type,
                    route_id,
                    int(output_budget_tokens),
                    int(completion_tokens),
                    route_fingerprint,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def get_interaction(self, *, interaction_id: str, user_id: str):
        with self._connection_factory() as conn:
            return conn.execute(
                "SELECT * FROM answer_interactions WHERE interaction_id = %s AND user_id = %s",
                (interaction_id, user_id),
            ).fetchone()

    def interaction_count(self, *, user_id: str) -> int:
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM answer_interactions WHERE user_id = %s",
                (user_id,),
            ).fetchone()
        return int(row["n"] or 0)

    def learned_target(self, *, user_id: str, task_type: str) -> int | None:
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT target_output_tokens FROM output_preferences WHERE user_id = %s AND task_type = %s",
                (user_id, task_type),
            ).fetchone()
        return int(row["target_output_tokens"]) if row else None

    def submit_feedback(
        self,
        *,
        user_id: str,
        interaction_id: str,
        rating: int,
        issues_json: str,
        expected_answer_description: str,
        comment: str,
        survey_id: str | None,
        survey_answers_json: str,
        too_long: bool,
        needs_more: bool,
        default_output_tokens: int,
        min_output_tokens: int,
        max_output_tokens: int,
        reward_reason: str,
        requested_credits: int,
        daily_reward_cap: int,
    ) -> tuple[bool, int, bool]:
        """Persist one feedback action atomically.

        Returns ``(duplicate, reward_credits, preference_updated)``.
        """
        now = datetime.now(timezone.utc).isoformat()
        day = now[:10]
        with self._connection_factory() as conn:
            require_active_tenant(conn, user_id=user_id)
            interaction = conn.execute(
                "SELECT * FROM answer_interactions WHERE interaction_id = %s AND user_id = %s FOR UPDATE",
                (interaction_id, user_id),
            ).fetchone()
            if interaction is None:
                raise ValueError("Unknown interaction_id for this user")

            duplicate = conn.execute(
                "SELECT 1 FROM answer_feedback WHERE user_id = %s AND interaction_id = %s",
                (user_id, interaction_id),
            ).fetchone()
            if duplicate:
                return True, 0, False

            conn.execute(
                """
                INSERT INTO answer_feedback(
                    user_id, interaction_id, rating, issues_json,
                    expected_answer_description, comment, survey_id,
                    survey_answers_json, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    interaction_id,
                    int(rating),
                    issues_json,
                    expected_answer_description,
                    comment,
                    survey_id,
                    survey_answers_json,
                    now,
                ),
            )

            preference_updated = False
            if too_long != needs_more:
                task_type = str(interaction["task_type"])
                current_budget = int(interaction["output_budget_tokens"] or 0)
                existing = conn.execute(
                    """
                    SELECT target_output_tokens, sample_count
                    FROM output_preferences
                    WHERE user_id = %s AND task_type = %s
                    FOR UPDATE
                    """,
                    (user_id, task_type),
                ).fetchone()
                base = (
                    int(existing["target_output_tokens"])
                    if existing
                    else max(min_output_tokens, current_budget or default_output_tokens)
                )
                adjusted = int(round(base * (0.80 if too_long else 1.25)))
                adjusted = max(min_output_tokens, min(max_output_tokens, adjusted))
                sample_count = int(existing["sample_count"] or 0) + 1 if existing else 1
                conn.execute(
                    """
                    INSERT INTO output_preferences(
                        user_id, task_type, target_output_tokens, sample_count, updated_at
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT(user_id, task_type) DO UPDATE SET
                        target_output_tokens = EXCLUDED.target_output_tokens,
                        sample_count = EXCLUDED.sample_count,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (user_id, task_type, adjusted, sample_count, now),
                )
                preference_updated = True

            rewarded = conn.execute(
                """
                SELECT COALESCE(SUM(credits), 0) AS rewarded
                FROM feedback_credit_ledger
                WHERE user_id = %s AND substring(created_at, 1, 10) = %s
                """,
                (user_id, day),
            ).fetchone()
            remaining = max(0, int(daily_reward_cap) - int(rewarded["rewarded"] or 0))
            reward = min(int(requested_credits), remaining)
            if reward > 0:
                inserted = conn.execute(
                    """
                    INSERT INTO feedback_credit_ledger(
                        user_id, interaction_id, reason, credits, created_at
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT(user_id, interaction_id, reason) DO NOTHING
                    RETURNING credits
                    """,
                    (user_id, interaction_id, reward_reason, reward, now),
                ).fetchone()
                if inserted is None:
                    reward = 0

        return False, reward, preference_updated

    def credit_balance(self, *, user_id: str) -> int:
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(credits), 0) AS balance FROM feedback_credit_ledger WHERE user_id = %s",
                (user_id,),
            ).fetchone()
        return int(row["balance"] or 0)

    def profile_rows(self, *, user_id: str) -> tuple[list[dict], list[dict]]:
        with self._connection_factory() as conn:
            preference_rows = conn.execute(
                "SELECT task_type, target_output_tokens FROM output_preferences WHERE user_id = %s",
                (user_id,),
            ).fetchall()
            feedback_rows = conn.execute(
                "SELECT issues_json, survey_id, survey_answers_json FROM answer_feedback WHERE user_id = %s",
                (user_id,),
            ).fetchall()
        return list(preference_rows), list(feedback_rows)

    def export_user_data(self, *, user_id: str) -> dict[str, list[dict]]:
        """Return all feedback-domain records owned by one tenant.

        Every query is scoped by ``user_id`` so privacy export cannot leak records
        from another tenant even when interaction identifiers overlap externally.
        """
        with self._connection_factory() as conn:
            interactions = conn.execute(
                "SELECT * FROM answer_interactions WHERE user_id = %s ORDER BY created_at, interaction_id",
                (user_id,),
            ).fetchall()
            feedback = conn.execute(
                "SELECT * FROM answer_feedback WHERE user_id = %s ORDER BY created_at, id",
                (user_id,),
            ).fetchall()
            credits = conn.execute(
                "SELECT * FROM feedback_credit_ledger WHERE user_id = %s ORDER BY created_at, id",
                (user_id,),
            ).fetchall()
            preferences = conn.execute(
                "SELECT * FROM output_preferences WHERE user_id = %s ORDER BY task_type",
                (user_id,),
            ).fetchall()
        return {
            "interactions": [dict(row) for row in interactions],
            "feedback": [dict(row) for row in feedback],
            "credit_ledger": [dict(row) for row in credits],
            "output_preferences": [dict(row) for row in preferences],
        }
