"""Feedback-aware facade over ModelRouter.

Keeps the stable provider-routing core small while adding a user-specific output budget,
interaction receipts, periodic survey offers, and a zero-LLM feedback loop.
"""

from __future__ import annotations

from app.config import Settings, get_settings
from app.models.model_router import ModelCatalogResponse, ModelRouteRequest, ModelRouteResponse
from app.services.feedback_service import FeedbackService
from app.services.model_router import ModelRouter, _resolve_task_type


class AdaptiveModelRouter:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        base_router: ModelRouter | None = None,
        feedback_service: FeedbackService | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._base = base_router or ModelRouter(self._settings)
        self._feedback = feedback_service or FeedbackService(self._settings)

    def route(self, request: ModelRouteRequest, *, user_id: str) -> ModelRouteResponse:
        task_type = _resolve_task_type(request)
        original_cap = request.max_output_tokens
        output_budget, preference_applied = self._feedback.resolve_output_budget(
            user_id=user_id,
            task_type=task_type.value,
            verbosity=request.verbosity.value,
            hard_cap=original_cap,
            adaptive=request.adaptive_output,
        )
        efficient_request = request.model_copy(
            update={
                "task_type": task_type,
                "max_output_tokens": output_budget,
            }
        )
        response = self._base.route(efficient_request, user_id=user_id)
        interaction_id = self._feedback.create_interaction_id()
        self._feedback.record_interaction(
            interaction_id=interaction_id,
            user_id=user_id,
            task_type=response.task_type.value,
            route_id=response.route_id,
            output_budget_tokens=output_budget,
            completion_tokens=response.usage.completion_tokens,
            route_fingerprint=response.route_fingerprint,
        )
        offer_survey = self._feedback.should_offer_survey(user_id=user_id)
        survey_reward = self._feedback.survey(user_id=user_id).reward_credits if offer_survey else 0
        return response.model_copy(
            update={
                "interaction_id": interaction_id,
                "output_budget_tokens": output_budget,
                "budget_tokens_saved_vs_cap": max(0, original_cap - output_budget),
                "preference_applied": preference_applied,
                "survey_available": offer_survey,
                "survey_reward_credits": survey_reward,
            }
        )

    def catalog(self, *, user_id: str) -> ModelCatalogResponse:
        return self._base.catalog(user_id=user_id)
