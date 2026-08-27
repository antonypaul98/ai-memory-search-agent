"""Deterministic learning-evolution signals derived from tenant-local usage.

The Memory Search product already records views and explicit helpful/not-helpful
feedback.  This module converts those signals into a deliberately small ranking
adjustment so the library can improve from use without re-ingesting content or
mutating the underlying retrieval/evidence score.
"""

from __future__ import annotations

from app.models.reflection import UsageStats

# Explicit feedback is the strongest learning signal.  Repeated views are a much
# weaker engagement signal.  Keep the total small so usage can break close ties
# but cannot rescue poor evidence.
_EXPLICIT_FEEDBACK_STEP = 0.01
_EXPLICIT_FEEDBACK_CAP = 0.03
_VIEW_STEP = 0.002
_VIEW_CAP = 0.01
_TOTAL_CAP = 0.04


def usage_learning_signal(usage: UsageStats | None) -> tuple[float, list[str]]:
    """Return a bounded ranking adjustment and explainable signal labels.

    Positive explicit feedback raises a close result; negative feedback lowers it.
    Repeated views add only a small positive preference signal.  Search counts are
    intentionally excluded because every retrieval records a search hit and would
    otherwise create a self-reinforcing ranking loop.
    """
    if usage is None:
        return 0.0, []

    helpful = max(0, int(getattr(usage, "helpful_count", 0) or 0))
    not_helpful = max(0, int(getattr(usage, "not_helpful_count", 0) or 0))
    views = max(0, int(getattr(usage, "view_count", 0) or 0))

    feedback_delta = helpful - not_helpful
    feedback_adjustment = max(
        -_EXPLICIT_FEEDBACK_CAP,
        min(_EXPLICIT_FEEDBACK_CAP, feedback_delta * _EXPLICIT_FEEDBACK_STEP),
    )
    view_bonus = min(_VIEW_CAP, views * _VIEW_STEP)

    adjustment = max(-_TOTAL_CAP, min(_TOTAL_CAP, feedback_adjustment + view_bonus))

    signals: list[str] = []
    if feedback_delta > 0:
        signals.append("helpful")
    elif feedback_delta < 0:
        signals.append("not_helpful")
    if views > 0:
        signals.append("viewed")

    return round(adjustment, 6), signals
