"""Regression tests for the Phase 1 legacy tenant metadata migration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.models.user import LOCAL_DEFAULT_USER_ID
from app.services.legacy_user_backfill import backfill_legacy_user_ids


def test_backfill_only_updates_rows_missing_user_id(test_settings) -> None:
    collection = MagicMock()
    collection.get.side_effect = [
        {
            "ids": ["legacy-1", "owned-1"],
            "metadatas": [
                {"video_id": "v1", "title": "Legacy"},
                {"video_id": "v2", "title": "Owned", "user_id": "user-a"},
            ],
        },
        {"ids": [], "metadatas": []},
    ]

    with patch("app.services.legacy_user_backfill.get_collection", return_value=collection):
        result = backfill_legacy_user_ids(test_settings, batch_size=2)

    assert result.scanned == 2
    assert result.legacy_found == 1
    assert result.updated == 1
    collection.update.assert_called_once_with(
        ids=["legacy-1"],
        metadatas=[
            {
                "video_id": "v1",
                "title": "Legacy",
                "user_id": LOCAL_DEFAULT_USER_ID,
            }
        ],
    )


def test_dry_run_never_writes(test_settings) -> None:
    collection = MagicMock()
    collection.get.return_value = {
        "ids": ["legacy-1"],
        "metadatas": [{"video_id": "v1"}],
    }

    with patch("app.services.legacy_user_backfill.get_collection", return_value=collection):
        result = backfill_legacy_user_ids(test_settings, batch_size=10, dry_run=True)

    assert result.legacy_found == 1
    assert result.updated == 0
    assert result.dry_run is True
    collection.update.assert_not_called()


def test_backfill_preserves_existing_metadata(test_settings) -> None:
    original = {
        "video_id": "v1",
        "source_type": "youtube",
        "connector_id": "youtube.v1",
        "url": "https://example.com/video",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    collection = MagicMock()
    collection.get.return_value = {"ids": ["legacy-1"], "metadatas": [original]}

    with patch("app.services.legacy_user_backfill.get_collection", return_value=collection):
        backfill_legacy_user_ids(test_settings, batch_size=10)

    written = collection.update.call_args.kwargs["metadatas"][0]
    for key, value in original.items():
        assert written[key] == value
    assert written["user_id"] == LOCAL_DEFAULT_USER_ID


def test_already_migrated_rows_are_idempotent(test_settings) -> None:
    collection = MagicMock()
    collection.get.return_value = {
        "ids": ["owned-1", "owned-2"],
        "metadatas": [
            {"video_id": "v1", "user_id": LOCAL_DEFAULT_USER_ID},
            {"video_id": "v2", "user_id": "user-a"},
        ],
    }

    with patch("app.services.legacy_user_backfill.get_collection", return_value=collection):
        result = backfill_legacy_user_ids(test_settings, batch_size=10)

    assert result.legacy_found == 0
    assert result.updated == 0
    collection.update.assert_not_called()


def test_rejects_invalid_batch_size(test_settings) -> None:
    with pytest.raises(ValueError, match="batch_size"):
        backfill_legacy_user_ids(test_settings, batch_size=0)
