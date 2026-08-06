"""Tests for reflection and usage registry."""

from app.db.video_registry import VideoRegistry, reset_video_registry_cache
from app.models.reflection import ReflectionInput, SaveReason


class TestVideoRegistry:
    def test_reflection_and_usage_persistence(self, test_settings) -> None:
        reset_video_registry_cache()
        registry = VideoRegistry(test_settings)
        reflection = ReflectionInput(
            save_reason=SaveReason.GOAL,
            goal="Build my AI workstation",
            reflection_note="Need a reliable parts list",
            recommendations_enabled=True,
        )
        registry.upsert_video(
            video_id="abc123",
            url="https://www.youtube.com/watch?v=abc123",
            title="PC Build Guide",
            channel="TechSource",
            reflection=reflection,
        )

        saved = registry.get_reflection("abc123")
        assert saved.goal == "Build my AI workstation"
        assert "AI workstation" in saved.reflection_message

        usage = registry.record_view("abc123")
        assert usage.view_count == 1
        assert usage.usage_summary.startswith("Viewed 1 time")

        registry.record_search(["abc123"])
        usage = registry.get_usage("abc123")
        assert usage.search_count == 1
