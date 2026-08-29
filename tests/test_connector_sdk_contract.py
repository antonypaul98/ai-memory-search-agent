"""F-29 connector SDK contract regression tests.

These tests lock the source-agnostic boundary promised by CONNECTOR_SDK.md.
They deliberately avoid network access and credentials.
"""

from app.services.sources import ConnectorRegistry
from app.services.sources.base_source import SourceConnector


def test_builtin_registry_exposes_unique_stable_connector_contracts() -> None:
    registry = ConnectorRegistry()
    connector_ids = registry.list_connectors()

    assert connector_ids == sorted(set(connector_ids))
    assert {"youtube.v1", "web.v1", "pdf.v1", "github.v1", "bookmarks.v1"}.issubset(
        connector_ids
    )

    for connector_id in connector_ids:
        connector = registry.get(connector_id)
        assert isinstance(connector, SourceConnector)
        assert connector.connector_id == connector_id
        assert connector.source_type is not None
        assert callable(connector.health)
        assert callable(connector.parse_ref)
        assert callable(connector.fetch_metadata)
        assert callable(connector.detect_transcript)
        assert callable(connector.fetch_transcript)


def test_registry_health_preserves_connector_identity_without_secrets() -> None:
    health = ConnectorRegistry().health_all()

    assert {item["connector_id"] for item in health} == set(
        ConnectorRegistry().list_connectors()
    )
    for item in health:
        assert set(item) == {"connector_id", "healthy", "detail"}
        assert isinstance(item["healthy"], bool)
