"""Jarvis-facing command routes.

The endpoint accepts text transcripts from any speech-to-text front end. Wake-word
recognition and audio capture stay outside the memory core; this layer only
requires a Jarvis wake phrase, normalizes the transcript, and delegates to the
existing agent command route so all confirmation and safety rules remain shared.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.api.routes.agent import agent_command
from app.models.agent import AgentCommandRequest, AgentCommandResponse
from app.models.user import UserPublic
from app.services.jarvis_command_adapter import (
    has_jarvis_wake_phrase,
    normalize_jarvis_command,
)

router = APIRouter(prefix="/jarvis", tags=["jarvis"])


@router.post("/voice", response_model=AgentCommandResponse)
def jarvis_voice_command(
    body: AgentCommandRequest,
    user: UserPublic = Depends(get_current_user),
) -> AgentCommandResponse:
    """Plan or execute a wake-word-prefixed spoken command transcript.

    Examples:
        ``Jarvis, search MCP servers``
        ``Hey Jarvis, tell me what I saved about Docker``

    A transcript without the Jarvis wake phrase is rejected to reduce accidental
    activation. Destructive/bulk behavior remains governed by ``agent_command``.
    """
    if not has_jarvis_wake_phrase(body.text):
        raise HTTPException(status_code=400, detail="Jarvis wake phrase required.")

    command = normalize_jarvis_command(body.text)
    if not command:
        raise HTTPException(status_code=400, detail="Command required after wake phrase.")

    normalized = body.model_copy(update={"text": command})
    return agent_command(normalized, user)
