"""
Grounded chat routes.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.api.dependencies import get_chat_service
from app.models.user import UserPublic
from app.models.chat import ChatRequest, ChatResponse
from app.services.chat_service import ChatService

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat_with_memories(
    body: ChatRequest,
    service: ChatService = Depends(get_chat_service),
    user: UserPublic = Depends(get_current_user),
) -> ChatResponse:
    """Answer a question using retrieved transcript chunks from saved videos."""
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    return service.chat(
        question=question,
        top_k=body.top_k,
        clarification_choice=body.clarification_choice,
        debug=body.debug,
        user_id=user.user_id,
    )
