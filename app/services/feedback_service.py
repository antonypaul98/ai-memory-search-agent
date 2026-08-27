"""Low-friction feedback loop, adaptive output budgets, and participation rewards.

The service is intentionally deterministic and local: collecting feedback must not spend
LLM tokens. Rewards are granted for participation, never for positive sentiment, so the
incentive is to provide honest signal rather than flattering ratings.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings, get_settings
from app.models.feedback import (
    FeedbackIssue,
    FeedbackProfile,
    FeedbackSubmitRequest,
    FeedbackSubmitResponse,
    FeedbackSurvey,
)

_QUICK_FEEDBACK_CREDITS = 5
_SURVEY_CREDITS = 20
_DAILY_REWARD_CAP = 100
_MIN_OUTPUT_TOKENS = 96
_MAX_ADAPTIVE_OUTPUT_TOKENS = 2048
_DEFAULT_OUTPUT_TOKENS = {
    "fast": 160,
    "extraction": 240,
    "general": 320,
    "summarization": 320,
    "reasoning": 640,
    "coding": 640,
}


class FeedbackService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._db_path = self._settings.sqlite_path
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self) -> None:
        with self._connect() as conn:
            conn.executescript(
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
                );
                CREATE INDEX IF NOT EXISTS idx_answer_interactions_user_time
                    ON answer_interactions(user_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS answer_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                );
                CREATE INDEX IF NOT EXISTS idx_answer_feedback_user_time
                    ON answer_feedback(user_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS feedback_credit_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    interaction_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    credits INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, interaction_id, reason)
                );
                CREATE INDEX IF NOT EXISTS idx_feedback_credits_user_time
                    ON feedback_credit_ledger(user_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS output_preferences (
                    user_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    target_output_tokens INTEGER NOT NULL,
                    sample_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, task_type)
                );
                """
            )

    def resolve_output_budget(
        self,
        *,
        user_id: str,
        task_type: str,
        verbosity: str,
        hard_cap: int,
        adaptive: bool = True,
    ) -> tuple[int, bool]:
        """Return the smallest reasonable output budget under the caller's hard cap."""
        cap = max(1, int(hard_cap))
        mode = (verbosity or "auto").lower()
        if mode == "detailed":
            return cap, False
        if mode == "concise":
            return min(cap, 192), False
        if mode == "balanced":
            return min(cap, 384), False
        if not adaptive:
            return cap, False

        learned = self._learned_target(user_id=user_id, task_type=task_type)
        target = learned if learned is not None else _DEFAULT_OUTPUT_TOKENS.get(task_type, 320)
        return min(cap, max(_MIN_OUTPUT_TOKENS, target)), learned is not None

    def create_interaction_id(self) -> str:
        return "ans_" + uuid.uuid4().hex

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
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO answer_interactions(
                    interaction_id, user_id, task_type, route_id,
                    output_budget_tokens, completion_tokens, route_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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

    def submit(self, *, user_id: str, request: FeedbackSubmitRequest) -> FeedbackSubmitResponse:
        with self._connect() as conn:
            interaction = conn.execute(
                "SELECT * FROM answer_interactions WHERE interaction_id = ? AND user_id = ?",
                (request.interaction_id, user_id),
            ).fetchone()
            if interaction is None:
                raise ValueError("Unknown interaction_id for this user")

            duplicate = conn.execute(
                "SELECT 1 FROM answer_feedback WHERE user_id = ? AND interaction_id = ?",
                (user_id, request.interaction_id),
            ).fetchone()
            if duplicate:
                return FeedbackSubmitResponse(
                    accepted=True,
                    reward_credits=0,
                    credit_balance=self.credit_balance(user_id=user_id),
                    preference_updated=False,
                    duplicate=True,
                )

            conn.execute(
                """
                INSERT INTO answer_feedback(
                    user_id, interaction_id, rating, issues_json,
                    expected_answer_description, comment, survey_id,
                    survey_answers_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    request.interaction_id,
                    request.rating,
                    json.dumps([issue.value for issue in request.issues]),
                    request.expected_answer_description.strip(),
                    request.comment.strip(),
                    request.survey_id,
                    json.dumps(request.survey_answers, sort_keys=True, default=str),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

            preference_updated = self._apply_length_feedback(
                conn,
                user_id=user_id,
                task_type=str(interaction["task_type"]),
                current_budget=int(interaction["output_budget_tokens"] or 0),
                issues=request.issues,
            )

            requested_reward = (
                _SURVEY_CREDITS
                if request.survey_id and request.survey_answers
                else _QUICK_FEEDBACK_CREDITS
            )
            reward = self._grant_reward(
                conn,
                user_id=user_id,
                interaction_id=request.interaction_id,
                requested_credits=requested_reward,
                reason="survey" if requested_reward == _SURVEY_CREDITS else "feedback",
            )

        return FeedbackSubmitResponse(
            accepted=True,
            reward_credits=reward,
            credit_balance=self.credit_balance(user_id=user_id),
            preference_updated=preference_updated,
            duplicate=False,
        )

    def survey(self, *, user_id: str) -> FeedbackSurvey:
        # Static questions are deliberate: generating a survey must cost zero model tokens.
        return FeedbackSurvey(
            survey_id="output-fit-v1",
            title="Help tune your answers",
            reward_credits=_SURVEY_CREDITS,
            questions=[
                {
                    "id": "matched_intent",
                    "type": "choice",
                    "question": "Did the answer match what you wanted?",
                    "options": ["yes", "partly", "no"],
                },
                {
                    "id": "length",
                    "type": "choice",
                    "question": "How was the answer length?",
                    "options": ["too_short", "right", "too_long"],
                },
                {
                    "id": "change",
                    "type": "text",
                    "question": "What one change would make the next answer better?",
                },
            ],
        )

    def should_offer_survey(self, *, user_id: str) -> bool:
        """Offer periodically, not after every answer: every fifth routed interaction."""
        with self._connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM answer_interactions WHERE user_id = ?",
                (user_id,),
            ).fetchone()["n"]
        return int(count or 0) > 0 and int(count) % 5 == 0

    def profile(self, *, user_id: str) -> FeedbackProfile:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT task_type, target_output_tokens FROM output_preferences WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            feedback_rows = conn.execute(
                "SELECT issues_json, survey_id, survey_answers_json FROM answer_feedback WHERE user_id = ?",
                (user_id,),
            ).fetchall()

        issue_counts: dict[str, int] = {}
        survey_count = 0
        for row in feedback_rows:
            try:
                issues = json.loads(row["issues_json"] or "[]")
            except json.JSONDecodeError:
                issues = []
            for issue in issues:
                issue_counts[str(issue)] = issue_counts.get(str(issue), 0) + 1
            if row["survey_id"] and row["survey_answers_json"] not in {"", "{}"}:
                survey_count += 1

        return FeedbackProfile(
            credit_balance=self.credit_balance(user_id=user_id),
            feedback_count=len(feedback_rows),
            survey_count=survey_count,
            target_output_tokens={str(row["task_type"]): int(row["target_output_tokens"]) for row in rows},
            issue_counts=issue_counts,
        )

    def credit_balance(self, *, user_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(credits), 0) AS balance FROM feedback_credit_ledger WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return int(row["balance"] or 0)

    def _learned_target(self, *, user_id: str, task_type: str) -> int | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT target_output_tokens FROM output_preferences WHERE user_id = ? AND task_type = ?",
                (user_id, task_type),
            ).fetchone()
        return int(row["target_output_tokens"]) if row else None

    def _apply_length_feedback(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        task_type: str,
        current_budget: int,
        issues: list[FeedbackIssue],
    ) -> bool:
        issue_values = {issue.value for issue in issues}
        too_long = FeedbackIssue.TOO_LONG.value in issue_values
        needs_more = bool(
            issue_values
            & {FeedbackIssue.TOO_SHORT.value, FeedbackIssue.MISSING_DETAIL.value}
        )
        if too_long == needs_more:  # neither or contradictory signal
            return False

        existing = conn.execute(
            "SELECT target_output_tokens, sample_count FROM output_preferences WHERE user_id = ? AND task_type = ?",
            (user_id, task_type),
        ).fetchone()
        base = (
            int(existing["target_output_tokens"])
            if existing
            else max(_MIN_OUTPUT_TOKENS, current_budget or _DEFAULT_OUTPUT_TOKENS.get(task_type, 320))
        )
        adjusted = int(round(base * (0.80 if too_long else 1.25)))
        adjusted = max(_MIN_OUTPUT_TOKENS, min(_MAX_ADAPTIVE_OUTPUT_TOKENS, adjusted))
        sample_count = int(existing["sample_count"] or 0) + 1 if existing else 1
        conn.execute(
            """
            INSERT INTO output_preferences(user_id, task_type, target_output_tokens, sample_count, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, task_type) DO UPDATE SET
                target_output_tokens = excluded.target_output_tokens,
                sample_count = excluded.sample_count,
                updated_at = excluded.updated_at
            """,
            (user_id, task_type, adjusted, sample_count, datetime.now(timezone.utc).isoformat()),
        )
        return True

    def _grant_reward(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        interaction_id: str,
        requested_credits: int,
        reason: str,
    ) -> int:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = conn.execute(
            """
            SELECT COALESCE(SUM(credits), 0) AS rewarded
            FROM feedback_credit_ledger
            WHERE user_id = ? AND substr(created_at, 1, 10) = ?
            """,
            (user_id, day),
        ).fetchone()
        remaining = max(0, _DAILY_REWARD_CAP - int(row["rewarded"] or 0))
        reward = min(int(requested_credits), remaining)
        if reward <= 0:
            return 0
        conn.execute(
            """
            INSERT OR IGNORE INTO feedback_credit_ledger(
                user_id, interaction_id, reason, credits, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_id,
                interaction_id,
                reason,
                reward,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return reward
