from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .models import FactSensitivity, MasterCareerProfile


class AnswerStatus(str, Enum):
    READY = "ready"
    CONFIRMATION_REQUIRED = "confirmation_required"


@dataclass(frozen=True, slots=True)
class ApplicationQuestion:
    question_id: str
    prompt: str
    fact_key: str
    require_locked_fact: bool = False

    def __post_init__(self) -> None:
        if not self.question_id.strip():
            raise ValueError("question_id must not be empty")
        if not self.prompt.strip():
            raise ValueError("application question prompt must not be empty")
        if not self.fact_key.strip():
            raise ValueError("application question fact_key must not be empty")


@dataclass(frozen=True, slots=True)
class GeneratedApplicationAnswer:
    question_id: str
    fact_key: str
    status: AnswerStatus
    text: str | None
    evidence_ref: str | None
    sensitivity: FactSensitivity


def generate_application_answer(
    profile: MasterCareerProfile,
    question: ApplicationQuestion,
    *,
    confirmed_locked_keys: Iterable[str] = (),
) -> GeneratedApplicationAnswer:
    """Generate a fact-grounded application answer without inventing content.

    Locked facts are never rendered until the caller explicitly confirms the
    exact canonical fact key for this generation attempt. This keeps sensitive
    answers such as work authorization, sponsorship, citizenship, salary, and
    criminal-history/EEO responses behind an explicit confirmation gate.
    """

    fact = profile.resolve_fact(question.fact_key)
    if question.require_locked_fact and fact.sensitivity is not FactSensitivity.LOCKED:
        raise PermissionError(
            f"application question requires a locked canonical fact: {question.fact_key}"
        )

    confirmed = set(confirmed_locked_keys)
    if fact.sensitivity is FactSensitivity.LOCKED and fact.key not in confirmed:
        return GeneratedApplicationAnswer(
            question_id=question.question_id,
            fact_key=fact.key,
            status=AnswerStatus.CONFIRMATION_REQUIRED,
            text=None,
            evidence_ref=fact.evidence_ref,
            sensitivity=fact.sensitivity,
        )

    return GeneratedApplicationAnswer(
        question_id=question.question_id,
        fact_key=fact.key,
        status=AnswerStatus.READY,
        text=str(fact.value),
        evidence_ref=fact.evidence_ref,
        sensitivity=fact.sensitivity,
    )


def generate_application_answers(
    profile: MasterCareerProfile,
    questions: Iterable[ApplicationQuestion],
    *,
    confirmed_locked_keys: Iterable[str] = (),
) -> tuple[GeneratedApplicationAnswer, ...]:
    confirmed = tuple(confirmed_locked_keys)
    return tuple(
        generate_application_answer(
            profile,
            question,
            confirmed_locked_keys=confirmed,
        )
        for question in questions
    )
