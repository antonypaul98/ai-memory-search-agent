from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings
from app.db.repositories.memory_repository import MemoryRepository
from app.models.user import LOCAL_DEFAULT_USER_ID


def _query_result(user_id: str | None = "user-a") -> dict:
    meta = {
        "user_id": user_id,
        "video_id": "v1",
        "title": "Demo",
        "channel": "Channel",
        "url": "https://example.com/v1",
    }
    if user_id is None:
        meta.pop("user_id")
    return {
        "documents": [["tenant memory"]],
        "metadatas": [[meta]],
        "distances": [[0.1]],
    }


def test_authenticated_user_search_pushes_user_filter_into_chroma() -> None:
    collection = MagicMock()
    collection.count.return_value = 10
    collection.query.return_value = _query_result("user-a")
    repo = MemoryRepository(Settings())

    with patch(
        "app.db.repositories.memory_repository.get_collection",
        return_value=collection,
    ):
        hits = repo.search([0.1, 0.2], 5, user_id="user-a")

    assert hits and hits[0]["video_id"] == "v1"
    kwargs = collection.query.call_args.kwargs
    assert kwargs["where"] == {"user_id": "user-a"}


def test_authenticated_user_never_falls_back_to_unscoped_query() -> None:
    collection = MagicMock()
    collection.count.return_value = 10
    collection.query.side_effect = RuntimeError("filter failure")
    repo = MemoryRepository(Settings())

    with patch(
        "app.db.repositories.memory_repository.get_collection",
        return_value=collection,
    ):
        with pytest.raises(RuntimeError, match="filter failure"):
            repo.search([0.1], 3, user_id="user-b")

    assert collection.query.call_count == 1
    assert collection.query.call_args.kwargs["where"] == {"user_id": "user-b"}


def test_local_default_can_use_legacy_fallback_but_still_post_filters() -> None:
    collection = MagicMock()
    collection.count.return_value = 10
    collection.query.side_effect = [RuntimeError("legacy schema"), _query_result(None)]
    repo = MemoryRepository(Settings())

    with patch(
        "app.db.repositories.memory_repository.get_collection",
        return_value=collection,
    ):
        hits = repo.search([0.1], 3, user_id=LOCAL_DEFAULT_USER_ID)

    assert len(hits) == 1
    assert collection.query.call_count == 2
    assert "where" in collection.query.call_args_list[0].kwargs
    assert "where" not in collection.query.call_args_list[1].kwargs
