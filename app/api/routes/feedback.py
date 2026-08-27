"""Answer feedback, survey, reward-credit, and learned-preference APIs."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.api.dependencies import get_feedback_service
from app.models.feedback import (
    FeedbackProfile,
    FeedbackSubmitRequest,
    FeedbackSubmitResponse,
    FeedbackSurvey,
)
from app.models.user import UserPublic
from app.services.feedback_service import FeedbackService

router = APIRouter(tags=["feedback"])


@router.post("/feedback", response_model=FeedbackSubmitResponse)
def submit_feedback(
    request: FeedbackSubmitRequest,
    service: FeedbackService = Depends(get_feedback_service),
    user: UserPublic = Depends(get_current_user),
) -> FeedbackSubmitResponse:
    try:
        return service.submit(user_id=user.user_id, request=request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/feedback/survey", response_model=FeedbackSurvey)
def get_feedback_survey(
    service: FeedbackService = Depends(get_feedback_service),
    user: UserPublic = Depends(get_current_user),
) -> FeedbackSurvey:
    return service.survey(user_id=user.user_id)


@router.get("/feedback/profile", response_model=FeedbackProfile)
def get_feedback_profile(
    service: FeedbackService = Depends(get_feedback_service),
    user: UserPublic = Depends(get_current_user),
) -> FeedbackProfile:
    return service.profile(user_id=user.user_id)
