"""Agent status and command routes for the Chrome extension (V1-1 / V1-7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.models.agent import (
    AgentCommandExecuteRequest,
    AgentCommandPlan,
    AgentCommandRequest,
    AgentCommandResponse,
    AgentStatusResponse,
)
from app.models.user import UserPublic
from app.services.agent_status_service import AgentStatusService
from app.services.command_router import BULK_INTENTS, CommandIntent, CommandRouterService

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/status", response_model=AgentStatusResponse)
def agent_status(user: UserPublic = Depends(get_current_user)) -> AgentStatusResponse:
    return AgentStatusService().get_status(user)


@router.post("/command", response_model=AgentCommandResponse)
def agent_command(
    body: AgentCommandRequest,
    user: UserPublic = Depends(get_current_user),
) -> AgentCommandResponse:
    """Classify a command into a plan; optionally execute safe intents."""
    router_svc = CommandRouterService()
    ctx = body.context.model_dump() if body.context else None
    plan_dict = router_svc.plan(body.text, user_id=user.user_id, context=ctx)
    plan = AgentCommandPlan(**plan_dict)

    if not body.execute:
        return AgentCommandResponse(
            plan=plan,
            executed=False,
            status="planned",
            message=plan.summary,
            result=None,
        )

    intent = (
        CommandIntent(plan.intent)
        if plan.intent in {i.value for i in CommandIntent}
        else CommandIntent.UNKNOWN
    )

    # Bulk intents: execute=true still requires confirm_token; never silent bulk write.
    if intent in BULK_INTENTS:
        if not body.confirm_token:
            return AgentCommandResponse(
                plan=plan,
                executed=False,
                status="confirm_required",
                message="Bulk action requires confirm_token after reviewing the plan.",
                result=None,
            )
        exec_result = router_svc.execute(
            user_id=user.user_id,
            intent=plan.intent,
            query=plan.query,
            original_text=plan.original_text or body.text,
            confirm_token=body.confirm_token,
            context=ctx,
            limit=body.limit,
        )
        # Drop confirm_token after successful consume so clients cannot replay the plan payload.
        if exec_result.get("ok"):
            plan = plan.model_copy(update={"confirm_token": None, "requires_confirm": False})
        return AgentCommandResponse(
            plan=plan,
            executed=bool(exec_result.get("ok")),
            status=str(exec_result.get("status") or "error"),
            message=str(exec_result.get("message") or ""),
            result=exec_result.get("result"),
        )

    exec_result = router_svc.execute(
        user_id=user.user_id,
        intent=plan.intent,
        query=plan.query,
        original_text=plan.original_text or body.text,
        confirm_token=body.confirm_token,
        context=ctx,
        limit=body.limit,
    )
    return AgentCommandResponse(
        plan=plan,
        executed=bool(exec_result.get("ok")),
        status=str(exec_result.get("status") or "error"),
        message=str(exec_result.get("message") or ""),
        result=exec_result.get("result"),
    )


@router.post("/command/execute", response_model=AgentCommandResponse)
def agent_command_execute(
    body: AgentCommandExecuteRequest,
    user: UserPublic = Depends(get_current_user),
) -> AgentCommandResponse:
    """Execute a planned command (confirm_token required for bulk intents)."""
    router_svc = CommandRouterService()
    ctx = body.context.model_dump() if body.context else None
    original = body.original_text or body.query or body.intent

    try:
        intent = CommandIntent(body.intent)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown intent: {body.intent}") from exc

    # Plan from original text for workspace URLs; override with client intent/query.
    plan_dict = router_svc.plan(
        original,
        user_id=user.user_id,
        context=ctx,
        issue_confirm_token=False,
    )
    plan_dict["intent"] = intent.value
    if body.query:
        plan_dict["query"] = body.query
    # Do not leak a freshly minted token from plan() on the execute path.
    plan_dict["confirm_token"] = None

    if intent in BULK_INTENTS:
        plan_dict["requires_confirm"] = True
        plan_dict["bulk"] = True

    if intent in BULK_INTENTS and not body.confirm_token:
        # Mint so the UI can recover a valid token after a missing-token call.
        from app.services.command_router import mint_confirm_token

        plan_dict["confirm_token"] = mint_confirm_token(
            user_id=user.user_id,
            intent=intent,
            query=(body.query or original).strip(),
        )
        plan = AgentCommandPlan(**plan_dict)
        return AgentCommandResponse(
            plan=plan,
            executed=False,
            status="confirm_required",
            message="Bulk action blocked without confirm_token.",
            result=None,
        )

    exec_result = router_svc.execute(
        user_id=user.user_id,
        intent=body.intent,
        query=body.query or plan_dict.get("query") or "",
        original_text=original,
        confirm_token=body.confirm_token,
        context=ctx,
        limit=body.limit,
    )

    # Never return a reusable confirm_token after successful bulk consume.
    if intent in BULK_INTENTS and exec_result.get("ok"):
        plan_dict["confirm_token"] = None
        plan_dict["requires_confirm"] = False
    elif intent in BULK_INTENTS and exec_result.get("status") == "confirm_required":
        # Invalid/replayed token — mint a fresh one for a clean retry.
        from app.services.command_router import mint_confirm_token

        plan_dict["confirm_token"] = mint_confirm_token(
            user_id=user.user_id,
            intent=intent,
            query=(body.query or original).strip(),
        )

    plan = AgentCommandPlan(**plan_dict)
    return AgentCommandResponse(
        plan=plan,
        executed=bool(exec_result.get("ok")),
        status=str(exec_result.get("status") or "error"),
        message=str(exec_result.get("message") or ""),
        result=exec_result.get("result"),
    )
