"""Jarvis V1 J01 core orchestration layer.

J01 deliberately reuses the accepted Memory Search command router and services.
It adds one authenticated natural-language entry point without creating a second
agent stack. Read-only intents may execute immediately; writes/bulk/external
actions remain behind the existing confirmation/handoff boundaries.
"""

from __future__ import annotations

from app.config import Settings, get_settings
from app.models.agent import AgentCommandPlan
from app.models.jarvis import JarvisRequest, JarvisResponse
from app.services.command_router import CommandIntent, CommandRouterService, SAFE_AUTO_EXECUTE


class JarvisCoreRuntime:
    """Plan and execute one bounded Jarvis turn over accepted Memory services."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._commands = CommandRouterService(self._settings)

    def run(self, *, user_id: str, request: JarvisRequest) -> JarvisResponse:
        owner = (user_id or "").strip()
        if not owner:
            raise ValueError("user_id is required")

        context = request.context.model_dump() if request.context else None
        plan_dict = self._commands.plan(
            request.text,
            user_id=owner,
            context=context,
            issue_confirm_token=False,
        )
        plan = AgentCommandPlan(**plan_dict)

        try:
            intent = CommandIntent(plan.intent)
        except ValueError:
            intent = CommandIntent.UNKNOWN

        # J01 is intentionally read-only by default. Later Jarvis gates can expose
        # approved action flows, but no natural-language request may bypass them.
        if intent not in SAFE_AUTO_EXECUTE:
            return JarvisResponse(
                plan=plan,
                executed=False,
                status="action_gated",
                message=(
                    "Jarvis planned the request but did not execute it because "
                    "this intent is not read-only."
                ),
                result=None,
            )

        outcome = self._commands.execute(
            user_id=owner,
            intent=plan.intent,
            query=plan.query,
            original_text=plan.original_text or request.text,
            context=context,
            limit=request.limit,
        )
        return JarvisResponse(
            plan=plan,
            executed=bool(outcome.get("ok")),
            status=str(outcome.get("status") or "error"),
            message=str(outcome.get("message") or ""),
            result=outcome.get("result"),
        )
