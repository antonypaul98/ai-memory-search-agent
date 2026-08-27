"""Phase 4d Review Agent: deterministic spaced-review queue over saved memories."""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import Settings
from app.db.video_registry import get_video_registry
from app.models.review_agent import ReviewItem, ReviewQueueRequest, ReviewQueueResponse
from app.services.review_schedule_service import ReviewScheduleService


class ReviewAgent:
    """Build a tenant-scoped review queue from reflection and usage metadata.

    Memories without review history use the stale-view threshold. Once a review
    result has been recorded, the durable review schedule becomes authoritative:
    future-due items stay out of the queue and due items re-enter it.
    """

    def __init__(self, settings: Settings) -> None:
        self._registry = get_video_registry(settings)
        self._schedule = ReviewScheduleService(settings)

    def queue(
        self,
        *,
        user_id: str,
        request: ReviewQueueRequest,
        now: datetime | None = None,
    ) -> ReviewQueueResponse:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)
        goal_filter = request.goal.strip().casefold()
        candidates: list[ReviewItem] = []

        for row in self._registry.list_videos(user_id=user_id):
            goal = str(row.get("goal") or "").strip()
            if not goal:
                continue
            if goal_filter and goal_filter not in goal.casefold():
                continue

            video_id = str(row["video_id"])
            schedule = self._schedule.get(user_id=user_id, video_id=video_id)
            if schedule:
                next_review = _parse_dt(schedule.get("next_review_at"))
                if next_review is not None and next_review > now:
                    continue
                # A scheduled item is due now regardless of ordinary view recency.
                age_days = None
            else:
                last_viewed = _parse_dt(row.get("last_viewed"))
                if last_viewed is not None:
                    age_days = max(0, (now - last_viewed).days)
                    if age_days < request.stale_days:
                        continue
                else:
                    age_days = None

            last_viewed = _parse_dt(row.get("last_viewed"))
            title = str(row.get("title") or "Untitled memory")
            save_reason = str(row.get("save_reason") or "")
            note = str(row.get("reflection_note") or "")
            prompt = _build_prompt(title=title, goal=goal, note=note)
            candidates.append(
                ReviewItem(
                    video_id=video_id,
                    title=title,
                    url=str(row.get("url") or ""),
                    channel=str(row.get("channel") or ""),
                    goal=goal,
                    save_reason=save_reason,
                    reflection_note=note,
                    last_viewed=(last_viewed.isoformat() if last_viewed else None),
                    saved_at=str(row.get("saved_at") or ""),
                    days_since_view=age_days,
                    prompt=prompt,
                )
            )

        # Never-viewed memories first, then stalest viewed memories, then oldest saves.
        candidates.sort(
            key=lambda item: (
                item.last_viewed is not None,
                -(item.days_since_view or 10**9),
                item.saved_at,
                item.video_id,
            )
        )
        total = len(candidates)
        return ReviewQueueResponse(
            goal=request.goal.strip(),
            stale_days=request.stale_days,
            total_candidates=total,
            items=candidates[: request.limit],
        )


def _parse_dt(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _build_prompt(*, title: str, goal: str, note: str) -> str:
    if note:
        return f"For your goal ‘{goal}’, what do you remember from ‘{title}’? Your earlier note was: {note}"
    return f"For your goal ‘{goal}’, what are the key ideas you remember from ‘{title}’?"
