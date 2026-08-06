"""Memory reflection, usage, and recommendation schemas."""

from enum import Enum

from pydantic import BaseModel, Field


class SaveReason(str, Enum):
    GOAL = "goal"
    PROJECT = "project"
    REFERENCE = "reference"
    FUTURE_LEARNING = "future_learning"
    ENTERTAINMENT = "entertainment"
    OTHER = "other"


class DifficultyLevel(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class PreferredStyle(str, Enum):
    VISUAL = "visual"
    SHORT = "short"
    DETAILED = "detailed"
    HANDS_ON = "hands_on"
    OFFICIAL_DOCUMENTATION = "official_documentation"


class ReflectionInput(BaseModel):
    """User-provided context when saving a memory."""

    save_reason: SaveReason = Field(default=SaveReason.GOAL)
    goal: str = Field(default="", description="What the user is working toward.")
    reflection_note: str = Field(default="", description="Why the user is saving this.")
    recommendations_enabled: bool = Field(default=True)
    preferred_creator_only: bool = Field(default=False)
    allow_other_creators: bool = Field(default=True)
    difficulty: DifficultyLevel = Field(default=DifficultyLevel.INTERMEDIATE)
    preferred_style: PreferredStyle = Field(default=PreferredStyle.HANDS_ON)


class UsageStats(BaseModel):
    """Per-video usage intelligence."""

    saved_at: str | None = None
    last_viewed: str | None = None
    view_count: int = 0
    search_count: int = 0
    last_searched: str | None = None
    helpful_count: int = 0
    not_helpful_count: int = 0

    @property
    def usage_summary(self) -> str:
        if self.view_count == 0:
            return "Never opened since saving"
        parts = [f"Viewed {self.view_count} time{'s' if self.view_count != 1 else ''}"]
        if self.last_viewed:
            parts.append(f"Last opened {self._relative_phrase(self.last_viewed)}")
        return " · ".join(parts)

    @staticmethod
    def _relative_phrase(iso_timestamp: str) -> str:
        from datetime import datetime, timezone

        try:
            then = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            days = max(0, (now - then).days)
            if days == 0:
                return "today"
            if days == 1:
                return "1 day ago"
            return f"{days} days ago"
        except ValueError:
            return "recently"


class ReflectionDisplay(BaseModel):
    """Reflection metadata shown in search and chat."""

    save_reason: str = ""
    goal: str = ""
    reflection_note: str = ""
    reflection_message: str = Field(
        default="",
        description="Human-readable reflection tying save intent to current query.",
    )
    recommendations_enabled: bool = False
    difficulty: str = ""
    preferred_style: str = ""


class RecommendationItem(BaseModel):
    """A preference-aware recommendation."""

    video_id: str
    title: str
    channel: str
    thumbnail: str = ""
    url: str
    why_recommended: str
    whats_different: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    already_saved: bool = True


class FeedbackRequest(BaseModel):
    helpful: bool
