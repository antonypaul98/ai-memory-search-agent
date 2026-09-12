"""Safety regression coverage for graph entity-merge backend selection."""

from __future__ import annotations

import pytest

from app.services.entity_merge_service import EntityMergeError, EntityMergeService


class _NonSqliteSelectedStore:
    """Sentinel selected backend that must never be routed into SQLite merge SQL."""

    def get_entity(self, *args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("selected backend should fail closed before entity reads")


def test_merge_fails_closed_before_sqlite_access_for_non_sqlite_backend(
    test_settings,
) -> None:
    service = EntityMergeService(test_settings, store=_NonSqliteSelectedStore())  # type: ignore[arg-type]

    with pytest.raises(EntityMergeError, match="selected graph backend"):
        service.merge(
            user_id="u1",
            target_entity_id="target",
            source_entity_id="source",
        )
