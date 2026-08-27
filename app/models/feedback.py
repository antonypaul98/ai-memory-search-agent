"""Feedback, survey, reward-credit, and output-preference contracts."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class FeedbackIssue(str, Enum):
    TOO_LONG = "too_long"
    TOO_SHORT = "too_short"
    INCORRECT = "incorrect"
    MISSING_DETAIL = "missing_detail"
    WRONG_TONE = "wrong_tone"
    WRONG_FORMAT = "wrong_format"
    IRRELEVANT = "irrelevant"
    SLOW = "slow"
    OTHER = "other"


class FeedbackSubmitRequest(BaseModel):
    interaction_id: str = Field(min_length=8, max_length=128)
    rating: int = Field(ge=1, le=5)
    issues: list[FeedbackIssue] = Field(default_factory=list, max_length=8)
    expected_answer_description: str = Field(default="", max_length=1000)
    comment: str = Field(default="", max_length=2000)
    survey_id: str | None = Field(default=None, max_length=128)
    survey_answers: dict[str, Any] = Field(default_factory=dict)


class FeedbackSubmitResponse(BaseModel):
    accepted: bool = True
    reward_credits: int = 0
    credit_balance: int = 0
    preference_updated: bool = False
    duplicate: bool = False


class FeedbackSurvey(BaseModel):
    survey_id: str
    title: str
    questions: list[dict[str, Any]] = Field(default_factory=list)
    reward_credits: int


class FeedbackProfile(BaseModel):
    credit_balance: int = 0
    feedback_count: int = 0
    survey_count: int = 0
    target_output_tokens: dict[str, int] = Field(default_factory=dict)
    issue_counts: dict[str, int] = Field(default_factory=dict)
