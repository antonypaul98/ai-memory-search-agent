"""
Grounded chat routes.
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.auth import get_current_user
from app.api.dependencies import get_app_settings, get_chat_service
from app.config import Settings
from app.models.user import UserPublic
from app.models.chat import ChatRequest, ChatResponse
from app.services.chat_service import ChatService
from app.services.event_bus import EventBus

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat_with_memories(
    body: ChatRequest,
    request: Request,
    service: ChatService = Depends(get_chat_service),
    user: UserPublic = Depends(get_current_user),
    settings: Settings = Depends(get_app_settings),
) -> ChatResponse:
    """Answer a question using retrieved transcript chunks from saved videos."""
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    response = service.chat(
        question=question,
        top_k=body.top_k,
        clarification_choice=body.clarification_choice,
        debug=body.debug,
        user_id=user.user_id,
    )
    EventBus(settings).emit(
        user_id=user.user_id,
        event_type="chat.completed",
        aggregate_type="chat",
        actor="user",
        request_id=getattr(request.state, "request_id", None),
        payload={
            "grounded": response.grounded,
            "needs_clarification": response.needs_clarification,
            "source_count": len(response.sources),
        },
    )
    return response
