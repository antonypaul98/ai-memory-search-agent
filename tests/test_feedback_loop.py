"""Tests for adaptive output budgets, feedback learning, and participation rewards."""

from __future__ import annotations

from app.models.feedback import FeedbackIssue, FeedbackSubmitRequest
from app.models.model_router import ModelRouteRequest, ModelTokenUsage, OutputVerbosity
from app.services.adaptive_model_router import AdaptiveModelRouter
from app.services.feedback_service import FeedbackService
from app.services.model_router import (
    ModelExecutionResult,
    ModelProfile,
    ModelRouter,
    ModelUsageLedger,
)


class BudgetCapturingExecutor:
    def __init__(self) -> None:
        self.budgets: list[int] = []

    def complete(self, profile: ModelProfile, request: ModelRouteRequest) -> ModelExecutionResult:
        self.budgets.append(request.max_output_tokens)
        return ModelExecutionResult(
            content="useful answer",
            usage=ModelTokenUsage(prompt_tokens=12, completion_tokens=20, total_tokens=32),
        )


def _profile() -> ModelProfile:
    return ModelProfile(
        provider_id="local",
        model_id="test-model",
        base_url="http://test.invalid",
        protocol="ollama",
        free_tier=True,
        capabilities=frozenset({"general", "fast", "reasoning", "coding", "summarization", "extraction"}),
        quality_score=0.8,
        estimated_latency_ms=50,
    )


def _adaptive_router(test_settings):
    executor = BudgetCapturingExecutor()
    base = ModelRouter(
        test_settings,
        profiles=[_profile()],
        executor=executor,
        ledger=ModelUsageLedger(test_settings),
    )
    feedback = FeedbackService(test_settings)
    return AdaptiveModelRouter(test_settings, base_router=base, feedback_service=feedback), feedback, executor


def test_auto_mode_uses_smaller_task_budget(test_settings) -> None:
    router, _feedback, executor = _adaptive_router(test_settings)

    result = router.route(ModelRouteRequest(prompt="Explain this simply", max_output_tokens=1000), user_id="u1")

    assert result.output_budget_tokens == 320
    assert result.budget_tokens_saved_vs_cap == 680
    assert executor.budgets == [320]
    assert result.interaction_id.startswith("ans_")


def test_detailed_mode_honors_full_user_cap(test_settings) -> None:
    router, _feedback, executor = _adaptive_router(test_settings)

    result = router.route(
        ModelRouteRequest(
            prompt="Give me the full explanation",
            max_output_tokens=900,
            verbosity=OutputVerbosity.DETAILED,
        ),
        user_id="u1",
    )

    assert result.output_budget_tokens == 900
    assert result.budget_tokens_saved_vs_cap == 0
    assert executor.budgets == [900]


def test_too_long_feedback_reduces_next_output_budget(test_settings) -> None:
    router, feedback, executor = _adaptive_router(test_settings)
    first = router.route(ModelRouteRequest(prompt="Explain this", max_output_tokens=1000), user_id="u1")

    submitted = feedback.submit(
        user_id="u1",
        request=FeedbackSubmitRequest(
            interaction_id=first.interaction_id,
            rating=3,
            issues=[FeedbackIssue.TOO_LONG],
            comment="Correct, but shorter next time.",
        ),
    )
    second = router.route(ModelRouteRequest(prompt="Explain another thing", max_output_tokens=1000), user_id="u1")

    assert submitted.preference_updated is True
    assert submitted.reward_credits == 5
    assert second.preference_applied is True
    assert second.output_budget_tokens == 256
    assert executor.budgets == [320, 256]


def test_too_short_feedback_increases_next_output_budget(test_settings) -> None:
    router, feedback, _executor = _adaptive_router(test_settings)
    first = router.route(ModelRouteRequest(prompt="Explain this", max_output_tokens=1000), user_id="u1")
    feedback.submit(
        user_id="u1",
        request=FeedbackSubmitRequest(
            interaction_id=first.interaction_id,
            rating=3,
            issues=[FeedbackIssue.TOO_SHORT],
        ),
    )

    second = router.route(ModelRouteRequest(prompt="Explain another thing", max_output_tokens=1000), user_id="u1")
    assert second.output_budget_tokens == 400


def test_rewards_participation_not_positive_rating(test_settings) -> None:
    router, feedback, _executor = _adaptive_router(test_settings)
    low = router.route(ModelRouteRequest(prompt="one"), user_id="u1")
    high = router.route(ModelRouteRequest(prompt="two"), user_id="u1")

    low_reward = feedback.submit(
        user_id="u1",
        request=FeedbackSubmitRequest(
            interaction_id=low.interaction_id,
            rating=1,
            issues=[FeedbackIssue.INCORRECT],
        ),
    )
    high_reward = feedback.submit(
        user_id="u1",
        request=FeedbackSubmitRequest(interaction_id=high.interaction_id, rating=5),
    )

    assert low_reward.reward_credits == 5
    assert high_reward.reward_credits == 5
    assert high_reward.credit_balance == 10


def test_completed_survey_has_larger_reward_and_duplicate_is_not_paid_twice(test_settings) -> None:
    router, feedback, _executor = _adaptive_router(test_settings)
    answer = router.route(ModelRouteRequest(prompt="one"), user_id="u1")
    request = FeedbackSubmitRequest(
        interaction_id=answer.interaction_id,
        rating=4,
        survey_id="output-fit-v1",
        survey_answers={"matched_intent": "yes", "length": "right", "change": "none"},
    )

    first = feedback.submit(user_id="u1", request=request)
    duplicate = feedback.submit(user_id="u1", request=request)

    assert first.reward_credits == 20
    assert first.credit_balance == 20
    assert duplicate.reward_credits == 0
    assert duplicate.duplicate is True
    assert duplicate.credit_balance == 20


def test_survey_is_periodic_not_every_answer(test_settings) -> None:
    router, _feedback, _executor = _adaptive_router(test_settings)
    results = [router.route(ModelRouteRequest(prompt=f"answer {i}"), user_id="u1") for i in range(5)]

    assert [result.survey_available for result in results] == [False, False, False, False, True]
    assert results[-1].survey_reward_credits == 20


def test_feedback_api_returns_profile_and_survey(client, test_settings) -> None:
    from app.api.dependencies import get_feedback_service
    from app.main import app

    feedback = FeedbackService(test_settings)
    interaction_id = feedback.create_interaction_id()
    feedback.record_interaction(
        interaction_id=interaction_id,
        user_id="local-default",
        task_type="general",
        route_id="local:test-model",
        output_budget_tokens=320,
        completion_tokens=20,
        route_fingerprint="route_test",
    )
    app.dependency_overrides[get_feedback_service] = lambda: feedback

    response = client.post(
        "/api/v1/feedback",
        json={
            "interaction_id": interaction_id,
            "rating": 3,
            "issues": ["too_long"],
        },
    )
    survey = client.get("/api/v1/feedback/survey")
    profile = client.get("/api/v1/feedback/profile")

    assert response.status_code == 200
    assert response.json()["reward_credits"] == 5
    assert survey.status_code == 200
    assert survey.json()["reward_credits"] == 20
    assert profile.status_code == 200
    assert profile.json()["target_output_tokens"]["general"] == 256
