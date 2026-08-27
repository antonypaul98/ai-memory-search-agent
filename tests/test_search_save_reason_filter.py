"""Regression tests for Phase 2 save-reason search filtering."""

from app.models.reflection import ReflectionDisplay
from app.models.video import SearchFilters, SearchResultItem
from app.services.search_service import _passes_filters


def _item(*, save_reason: str) -> SearchResultItem:
    return SearchResultItem(
        video_id="v1",
        title="RAG Architecture",
        channel="Builder Channel",
        thumbnail="",
        url="https://www.youtube.com/watch?v=v1",
        original_url="https://www.youtube.com/watch?v=v1",
        timestamp_url="https://www.youtube.com/watch?v=v1&t=1s",
        matched_text="retrieval augmented generation",
        relevance_score=0.9,
        why_matched="Transcript passage matched",
        save_reason=save_reason,
        reflection=ReflectionDisplay(save_reason=save_reason),
    )


def test_save_reason_filter_matches_case_insensitive_substring() -> None:
    item = _item(save_reason="Reference for my Interview Prep project")
    assert _passes_filters(item, SearchFilters(save_reason="interview prep")) is True
    assert _passes_filters(item, SearchFilters(save_reason="REFERENCE")) is True


def test_save_reason_filter_rejects_non_matching_memory() -> None:
    item = _item(save_reason="Reference for my Interview Prep project")
    assert _passes_filters(item, SearchFilters(save_reason="home lab")) is False


def test_save_reason_filter_does_not_match_empty_private_metadata() -> None:
    item = _item(save_reason="")
    assert _passes_filters(item, SearchFilters(save_reason="project")) is False


def test_search_filters_serializes_save_reason_for_filters_applied() -> None:
    filters = SearchFilters(channel="builder", save_reason="project")
    dumped = filters.model_dump(exclude_none=True)
    assert dumped["channel"] == "builder"
    assert dumped["save_reason"] == "project"
