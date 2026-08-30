"""Static acceptance checks for the F-33 reviewed entity-merge workspace."""

from pathlib import Path


def _topics_source() -> str:
    return Path("app/static/js/views/topics.js").read_text(encoding="utf-8")


def test_topics_workspace_exposes_reviewed_entity_merge() -> None:
    source = _topics_source()
    assert "Entity merge review" in source
    assert "/knowledge/entities?limit=100" in source
    assert "Only same-type entities can be merged" in source
    assert "window.confirm" in source
    assert "confirm: true" in source
    assert "/knowledge/entities/${encodeURIComponent(targetEntity.entity_id)}/merge" in source


def test_entity_merge_ui_does_not_offer_memory_entities() -> None:
    source = _topics_source()
    assert 'entity.entity_type !== "memory"' in source
    assert "targetEntity.entity_type !== sourceEntity.entity_type" in source
