from pathlib import Path

import app.db.hierarchical_store as hierarchical_store


def test_hierarchical_store_has_no_legacy_relational_capsule_writer():
    """Keep the Chroma hierarchy module out of the relational SQLite path."""

    assert not hasattr(hierarchical_store, "store_capsule_json")

    source = Path(hierarchical_store.__file__).read_text(encoding="utf-8")
    assert "app.db.schema" not in source
    assert "sqlite3" not in source
    assert "memory_capsules_json" not in source
