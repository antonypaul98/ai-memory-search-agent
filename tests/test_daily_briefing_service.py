from datetime import datetime, timezone

import pytest

from app.services.daily_briefing_service import BriefingSignal, DailyBriefingService


def signal(signal_id: str, kind: str, priority: int = 0, tenant: str = "tenant-a") -> BriefingSignal:
    return BriefingSignal(
        tenant_id=tenant,
        signal_id=signal_id,
        kind=kind,
        summary=f"summary-{signal_id}",
        priority=priority,
        evidence_ids=(f"evidence-{signal_id}",),
    )


def test_compose_combines_review_gap_and_goal_outputs_deterministically():
    service = DailyBriefingService()
    now = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)

    briefing = service.compose(
        tenant_id="tenant-a",
        review_signals=[signal("r-low", "review", 1), signal("r-high", "review", 9)],
        gap_signals=[signal("g-1", "gap", 3)],
        goal_signals=[signal("goal-1", "goal", 4)],
        generated_at=now,
    )

    assert briefing.generated_at == now
    assert [item.signal_id for item in briefing.sections["review"]] == ["r-high", "r-low"]
    assert [item.signal_id for item in briefing.sections["gap"]] == ["g-1"]
    assert [item.signal_id for item in briefing.sections["goal"]] == ["goal-1"]
    assert briefing.sections["review"][0].evidence_ids == ("evidence-r-high",)


def test_compose_rejects_cross_tenant_signals():
    with pytest.raises(ValueError, match="cross-tenant"):
        DailyBriefingService().compose(
            tenant_id="tenant-a",
            review_signals=[signal("foreign", "review", tenant="tenant-b")],
        )


def test_notifications_are_opt_in_and_require_global_enablement():
    service = DailyBriefingService()
    assert service.compose(tenant_id="tenant-a").notification_allowed is False
    assert service.compose(
        tenant_id="tenant-a",
        notification_preferences={"daily_briefing": True, "notifications_enabled": False},
    ).notification_allowed is False
    assert service.compose(
        tenant_id="tenant-a",
        notification_preferences={"daily_briefing": True, "notifications_enabled": True},
    ).notification_allowed is True


def test_section_bounds_and_stable_tie_breaking():
    briefing = DailyBriefingService().compose(
        tenant_id="tenant-a",
        review_signals=[signal("b", "review", 1), signal("a", "review", 1)],
        max_items_per_section=1,
    )
    assert [item.signal_id for item in briefing.sections["review"]] == ["a"]


def test_naive_generated_at_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        DailyBriefingService().compose(
            tenant_id="tenant-a",
            generated_at=datetime(2026, 9, 23, 12),
        )
