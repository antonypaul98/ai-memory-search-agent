"""Reverse Memory: turn detected goal gaps into deterministic next-learning actions."""

from __future__ import annotations

from app.config import Settings
from app.models.gap_agent import GapAnalysisRequest
from app.models.reverse_memory import (
    LearningNextSuggestion,
    ReverseMemoryRequest,
    ReverseMemoryResponse,
)
from app.services.gap_agent import GapAgent


class ReverseMemoryService:
    """Recommend what to learn/review next using only grounded gap evidence."""

    def __init__(self, settings: Settings) -> None:
        self._gaps = GapAgent(settings)

    def suggest(
        self,
        *,
        user_id: str,
        request: ReverseMemoryRequest,
    ) -> ReverseMemoryResponse:
        gaps = self._gaps.analyze(
            user_id=user_id,
            request=GapAnalysisRequest(
                goals=request.goals,
                min_memories=request.min_memories,
                min_sources=request.min_sources,
                stale_days=request.stale_days,
                limit=max(request.limit, len(request.goals) or request.limit),
            ),
        )

        suggestions: list[LearningNextSuggestion] = []
        for report in gaps.reports:
            kinds = {finding.kind: finding for finding in report.findings}

            if report.memory_count == 0 and "coverage" in kinds:
                finding = kinds["coverage"]
                suggestions.append(
                    LearningNextSuggestion(
                        goal=report.goal,
                        priority=1,
                        kind="start_foundation",
                        reason=finding.message,
                        action=f"Start by saving one strong foundational source for ‘{report.goal}’. Then add at least one independent source before relying on the topic.",
                        evidence=finding.evidence,
                    )
                )
                continue

            if "review" in kinds:
                finding = kinds["review"]
                suggestions.append(
                    LearningNextSuggestion(
                        goal=report.goal,
                        priority=1,
                        kind="review_existing",
                        reason=finding.message,
                        action=f"Review your stale ‘{report.goal}’ memories first; reuse what you already saved before collecting more.",
                        evidence=finding.evidence,
                    )
                )

            if "coverage" in kinds:
                finding = kinds["coverage"]
                suggestions.append(
                    LearningNextSuggestion(
                        goal=report.goal,
                        priority=2,
                        kind="expand_coverage",
                        reason=finding.message,
                        action=f"Add more directly relevant evidence for ‘{report.goal}’ until the minimum coverage target is met.",
                        evidence=finding.evidence,
                    )
                )

            if "source_diversity" in kinds:
                finding = kinds["source_diversity"]
                suggestions.append(
                    LearningNextSuggestion(
                        goal=report.goal,
                        priority=3,
                        kind="diversify_sources",
                        reason=finding.message,
                        action=f"Learn ‘{report.goal}’ from a different creator, site, or connector so one source does not dominate your memory.",
                        evidence=finding.evidence,
                    )
                )

        suggestions.sort(key=lambda item: (item.priority, item.goal.casefold(), item.kind))
        return ReverseMemoryResponse(
            suggestions=suggestions[: request.limit],
            total=len(suggestions),
            goals_analyzed=gaps.goals_analyzed,
        )
