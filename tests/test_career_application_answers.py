import pytest

from app.career import (
    AnswerStatus,
    ApplicationQuestion,
    CareerFact,
    FactSensitivity,
    FactSource,
    MasterCareerProfile,
    generate_application_answer,
    generate_application_answers,
)


def _profile() -> MasterCareerProfile:
    profile = MasterCareerProfile(tenant_id="tenant-a")
    profile.add_fact(
        CareerFact(
            key="work_authorization",
            value="verified-status",
            source=FactSource.USER,
            sensitivity=FactSensitivity.LOCKED,
            evidence_ref="user-confirmation:work-auth",
        )
    )
    profile.add_fact(
        CareerFact(
            key="preferred_title",
            value="QA Automation Engineer",
            source=FactSource.USER,
            evidence_ref="user-profile:title",
        )
    )
    return profile


def test_locked_answer_is_not_rendered_without_confirmation():
    answer = generate_application_answer(
        _profile(),
        ApplicationQuestion(
            question_id="q1",
            prompt="What is your work authorization?",
            fact_key="work_authorization",
            require_locked_fact=True,
        ),
    )

    assert answer.status is AnswerStatus.CONFIRMATION_REQUIRED
    assert answer.text is None
    assert answer.evidence_ref == "user-confirmation:work-auth"


def test_locked_answer_renders_only_after_exact_fact_confirmation():
    profile = _profile()
    question = ApplicationQuestion(
        question_id="q1",
        prompt="What is your work authorization?",
        fact_key="work_authorization",
        require_locked_fact=True,
    )

    wrong_confirmation = generate_application_answer(
        profile,
        question,
        confirmed_locked_keys=("sponsorship_required",),
    )
    confirmed = generate_application_answer(
        profile,
        question,
        confirmed_locked_keys=("work_authorization",),
    )

    assert wrong_confirmation.text is None
    assert wrong_confirmation.status is AnswerStatus.CONFIRMATION_REQUIRED
    assert confirmed.text == "verified-status"
    assert confirmed.status is AnswerStatus.READY


def test_protected_question_rejects_non_locked_fact():
    with pytest.raises(PermissionError, match="requires a locked canonical fact"):
        generate_application_answer(
            _profile(),
            ApplicationQuestion(
                question_id="q2",
                prompt="Protected answer",
                fact_key="preferred_title",
                require_locked_fact=True,
            ),
        )


def test_unknown_fact_is_rejected_instead_of_invented():
    with pytest.raises(KeyError, match="unknown canonical career fact"):
        generate_application_answer(
            _profile(),
            ApplicationQuestion(
                question_id="q3",
                prompt="Do you know Kubernetes?",
                fact_key="skill.kubernetes",
            ),
        )


def test_batch_generation_preserves_question_order_and_evidence():
    answers = generate_application_answers(
        _profile(),
        (
            ApplicationQuestion("q-title", "Preferred title?", "preferred_title"),
            ApplicationQuestion(
                "q-auth",
                "Work authorization?",
                "work_authorization",
                require_locked_fact=True,
            ),
        ),
    )

    assert [answer.question_id for answer in answers] == ["q-title", "q-auth"]
    assert answers[0].text == "QA Automation Engineer"
    assert answers[0].evidence_ref == "user-profile:title"
    assert answers[1].text is None
    assert answers[1].status is AnswerStatus.CONFIRMATION_REQUIRED
