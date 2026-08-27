"""Regression tests for tenant-scoped trust badges on search results."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.models.reflection import ReflectionDisplay, UsageStats
from app.services.search_service import _to_search_result_item


def _hit() -> dict:
    return {
        "video_id": "v1",
        "title": "Trusted RAG Guide",
        "channel": "Demo",
        "thumbnail": "",
        "url": "https://www.youtube.com/watch?v=v1",
        "matched_text": "RAG retrieves evidence before generation.",
        "relevance_score": 0.81,
        "source_type": "youtube",
        "connector_id": "youtube.v1",
    }


def _registry() -> MagicMock:
    registry = MagicMock()
    registry.get_reflection.return_value = ReflectionDisplay()
    registry.get_usage.return_value = UsageStats()
    return registry


class TestTrustBadges:
    def test_search_result_exposes_persisted_trust_for_current_tenant(self) -> None:
        store = MagicMock()
        store.get_by_external.return_value = SimpleNamespace(
            verification_status=SimpleNamespace(value="verified"),
            trust=SimpleNamespace(
                overall=0.84,
                tier=SimpleNamespace(value="trusted"),
            ),
        )
        yt_store = MagicMock()
        yt_store.get.return_value = None

        item = _to_search_result_item(
            hit=_hit(),
            query="rag evidence",
            registry=_registry(),
            yt_store=yt_store,
            memory_store=store,
            user_id="tenant-a",
        )

        assert item.trust_score == 0.84
        assert item.trust_tier == "trusted"
        assert item.verification_status == "verified"
        store.get_by_external.assert_called_once_with(
            user_id="tenant-a",
            source_type="youtube",
            external_id="v1",
        )

    def test_missing_trust_does_not_invent_badge(self) -> None:
        store = MagicMock()
        store.get_by_external.return_value = None
        yt_store = MagicMock()
        yt_store.get.return_value = None

        item = _to_search_result_item(
            hit=_hit(),
            query="rag",
            registry=_registry(),
            yt_store=yt_store,
            memory_store=store,
            user_id="tenant-b",
        )

        assert item.trust_score is None
        assert item.trust_tier is None
        assert item.verification_status is None

    def test_trust_store_failure_does_not_break_search(self) -> None:
        store = MagicMock()
        store.get_by_external.side_effect = RuntimeError("trust store unavailable")
        yt_store = MagicMock()
        yt_store.get.return_value = None

        item = _to_search_result_item(
            hit=_hit(),
            query="rag",
            registry=_registry(),
            yt_store=yt_store,
            memory_store=store,
            user_id="tenant-a",
        )

        assert item.video_id == "v1"
        assert item.trust_score is None
        assert item.trust_tier is None
