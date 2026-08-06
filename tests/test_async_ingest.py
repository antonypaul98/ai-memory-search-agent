"""Tests for async ingest behavior."""

from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings
from app.models.reflection import ReflectionInput, SaveReason
from app.models.video import IngestResultItem
from app.services.ingest_service import IngestService


class TestAsyncIngest:
    def test_deduplicates_duplicate_video_ids(self, test_settings: Settings) -> None:
        service = IngestService(settings=test_settings)
        with patch.object(service, "_ingest_one") as mock_ingest:
            mock_ingest.return_value = IngestResultItem(url="x", success=True)
            response = service.ingest_batch(
                [
                    "https://www.youtube.com/watch?v=abc12345678",
                    "https://youtu.be/abc12345678",
                ]
            )
        assert response.total == 1
        mock_ingest.assert_called_once()

    def test_skips_already_indexed_video(self, test_settings: Settings) -> None:
        service = IngestService(settings=test_settings)
        registry = service._registry
        registry.upsert_video(
            video_id="abc12345678",
            url="https://www.youtube.com/watch?v=abc12345678",
            title="Existing",
            channel="Creator",
        )
        assert registry.is_indexed("abc12345678")
        with patch.object(service._metadata, "fetch_metadata") as mock_meta:
            response = service.ingest_batch(
                ["https://www.youtube.com/watch?v=abc12345678"],
                force_refresh=False,
            )
        mock_meta.assert_not_called()
        assert response.skipped == 1
        assert response.results[0].skipped is True

    def test_stores_reflection_metadata(self, test_settings: Settings) -> None:
        service = IngestService(settings=test_settings)
        reflection = ReflectionInput(
            save_reason=SaveReason.PROJECT,
            goal="Demo project",
            reflection_note="Leadership demo",
        )
        with patch.object(service, "_ingest_one") as mock_ingest:
            mock_ingest.return_value = IngestResultItem(
                url="https://www.youtube.com/watch?v=abc12345678",
                success=True,
                elapsed_ms=10.0,
            )
            service.ingest_batch(
                ["https://www.youtube.com/watch?v=abc12345678"],
                reflection=reflection,
            )
        assert mock_ingest.call_args.kwargs["reflection"] == reflection

    def test_batch_limit_raises(self, test_settings: Settings) -> None:
        service = IngestService(settings=test_settings)
        with pytest.raises(ValueError):
            service.ingest_batch(["https://youtu.be/x"] * 21)
