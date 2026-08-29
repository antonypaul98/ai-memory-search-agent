"""Phase 4 Gap Agent: deterministic learning-gap analysis over reflection goals."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse

from app.config import Settings
from app.db.video_registry import get_video_registry
from app.models.gap_agent import (
    GapAnalysisRequest,
    GapAnalysisResponse,
    GapFinding,
    GoalGapNotification,
    GoalGapReport,
)


class GapAgent:
    """Analyze coverage holes for active goals without writing memory.

    The agent uses only the authenticated user's registry/reflection metadata. It
    emits deterministic, evidence-backed suggestions instead of inventing topics
    or fetching external information.
    """

    def __init__(self, settings: Settings) -> None:
        self._registry = get_video_registry(settings)

    def analyze(
        self,
        *,
        user_id: str,
        request: GapAnalysisRequest,
        now: datetime | None = None,
    ) -> GapAnalysisResponse:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)

        requested = {_norm_goal(g): g.strip() for g in request.goals if g.strip()}
        grouped: dict[str, list[dict]] = defaultdict(list)
        display: dict[str, str] = {}

        for row in self._registry.list_videos(user_id=user_id):
            goal = str(row.get("goal") or "").strip()
            if not goal:
                continue
            key = _norm_goal(goal)
            if requested and key not in requested:
                continue
            grouped[key].append(row)
            display.setdefault(key, goal)

        # Explicitly requested goals with zero saved memories must still be analyzed.
        for key, original in requested.items():
            grouped.setdefault(key, [])
            display.setdefault(key, original)

        reports: list[GoalGapReport] = []
        for key in sorted(grouped, key=lambda k: display[k].casefold()):
            rows = grouped[key]
            sources = {_source_key(row) for row in rows if _source_key(row)}
            stale = sum(1 for row in rows if _is_stale(row.get("last_viewed"), now, request.stale_days))
            findings: list[GapFinding] = []

            if len(rows) < request.min_memories:
                findings.append(
                    GapFinding(
                        kind="coverage",
                        severity="high" if not rows else "medium",
                        message=f"Only {len(rows)} saved memories support this goal; target is {request.min_memories}.",
                        action="Save or ingest more evidence directly related to this goal.",
                        evidence={"memory_count": len(rows), "minimum": request.min_memories},
                    )
                )

            if len(sources) < request.min_sources:
                findings.append(
                    GapFinding(
                        kind="source_diversity",
                        severity="medium",
                        message=f"This goal currently draws from {len(sources)} distinct source(s); target is {request.min_sources}.",
                        action="Add evidence from a different creator, site, or connector before treating the topic as well covered.",
                        evidence={"distinct_sources": len(sources), "minimum": request.min_sources},
                    )
                )

            if stale:
                findings.append(
                    GapFinding(
                        kind="review",
                        severity="low" if stale < len(rows) else "medium",
                        message=f"{stale} memory item(s) for this goal are unreviewed or stale by {request.stale_days}+ days.",
                        action="Review the stale memories before collecting more material.",
                        evidence={"stale_or_never_viewed": stale, "stale_days": request.stale_days},
                    )
                )

            if findings:
                reports.append(
                    GoalGapReport(
                        goal=display[key],
                        memory_count=len(rows),
                        distinct_sources=len(sources),
                        stale_or_never_viewed=stale,
                        findings=findings,
                    )
                )

        limited_reports = reports[: request.limit]
        notifications = [
            GoalGapNotification(
                goal=report.goal,
                message=f"{report.goal} has {len(report.findings)} actionable learning gap(s).",
                actions=[finding.action for finding in report.findings if finding.action.strip()],
            )
            for report in limited_reports
        ]
        return GapAnalysisResponse(
            goals_analyzed=len(grouped),
            goals_with_gaps=len(reports),
            reports=limited_reports,
            notifications=notifications,
        )


def _norm_goal(value: str) -> str:
    return " ".join(value.casefold().split())


def _source_key(row: dict) -> str:
    channel = str(row.get("channel") or "").strip().casefold()
    if channel:
        return f"channel:{channel}"
    url = str(row.get("url") or "").strip()
    if not url:
        return ""
    host = (urlparse(url).hostname or "").casefold()
    return f"host:{host}" if host else ""


def _is_stale(value: object, now: datetime, stale_days: int) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return True
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (now - parsed.astimezone(timezone.utc)).days >= stale_days
