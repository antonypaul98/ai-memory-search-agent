"""Deterministic, tenant-safe daily briefing composition.

U03/G27 deliberately composes already-derived signals; it does not invoke AI,
mutate memory, or bypass the confirmation/notification boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class BriefingSignal:
    tenant_id: str
    signal_id: str
    kind: str
    summary: str
    priority: int = 0
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DailyBriefing:
    tenant_id: str
    generated_at: datetime
    sections: Mapping[str, tuple[BriefingSignal, ...]]
    notification_allowed: bool


class DailyBriefingService:
    """Compose bounded briefing sections from trusted upstream outputs."""

    SECTION_ORDER = ("review", "gap", "goal")

    def compose(
        self,
        *,
        tenant_id: str,
        review_signals: Iterable[BriefingSignal] = (),
        gap_signals: Iterable[BriefingSignal] = (),
        goal_signals: Iterable[BriefingSignal] = (),
        notification_preferences: Mapping[str, bool] | None = None,
        generated_at: datetime | None = None,
        max_items_per_section: int = 5,
    ) -> DailyBriefing:
        if not tenant_id.strip():
            raise ValueError("tenant_id is required")
        if max_items_per_section < 1:
            raise ValueError("max_items_per_section must be >= 1")

        raw: Sequence[tuple[str, Iterable[BriefingSignal]]] = (
            ("review", review_signals),
            ("gap", gap_signals),
            ("goal", goal_signals),
        )
        sections: dict[str, tuple[BriefingSignal, ...]] = {}
        for section, signals in raw:
            validated = []
            for signal in signals:
                if signal.tenant_id != tenant_id:
                    raise ValueError("cross-tenant briefing signal rejected")
                if not signal.signal_id or not signal.summary.strip():
                    raise ValueError("briefing signals require id and summary")
                validated.append(signal)
            validated.sort(key=lambda item: (-item.priority, item.signal_id))
            sections[section] = tuple(validated[:max_items_per_section])

        preferences = notification_preferences or {}
        notification_allowed = bool(
            preferences.get("daily_briefing", False)
            and preferences.get("notifications_enabled", False)
        )
        now = generated_at or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("generated_at must be timezone-aware")

        return DailyBriefing(
            tenant_id=tenant_id,
            generated_at=now,
            sections=sections,
            notification_allowed=notification_allowed,
        )
