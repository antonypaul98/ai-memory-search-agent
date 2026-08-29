# F-29 Connector SDK Closeout

**Feature:** F-29 — Pluggable Source Framework  
**Scope:** Memory Search Agent only  
**Result:** Functional SDK v1 acceptance validated; canonical status reconciliation follows this evidence.

## Validated implementation

The repository no longer has only source stubs. The active connector boundary is `SourceConnector` in `app/services/sources/base_source.py`, with normalized source references, normalized metadata, transcript payloads, health, parsing, metadata fetch, transcript detection, and transcript fetch contracts.

`ConnectorRegistry` in `app/services/sources/__init__.py` provides deterministic connector lookup and URL resolution. It supports a configuration allowlist, rejects unknown configured connector IDs fail-closed, and currently registers the built-in YouTube, web, PDF, GitHub, bookmarks, Google Drive, podcast, Readwise, and Notion connectors.

The ingestion path has `ConnectorIngestService`, and existing regression suites cover the core V1 connector families, configuration filtering, source normalization, deterministic cross-connector duplicate detection, and connector-specific import behavior.

## SDK v1 acceptance evidence

- [x] A common `SourceConnector` contract is implemented and enforced by the built-in registry.
- [x] `youtube.v1` remains registered behind the connector boundary while existing YouTube tests remain in CI.
- [x] `web.v1` normalization/ingest behavior is covered by offline regression tests.
- [x] Connector enablement is configuration-driven through `CONNECTOR_ENABLED_IDS`; unknown configured IDs fail closed.
- [x] Connector health is available through the registry without exposing credentials or arbitrary connector state.
- [x] Core V1 connectors preserve stable connector IDs and source types.
- [x] Cross-source ingestion retains tenant-scoped canonical/provenance records and deterministic duplicate checks rather than introducing connector-specific storage shortcuts.

## Regression added at closeout

`tests/test_connector_sdk_contract.py` locks the built-in registry to the source-agnostic contract, verifies stable unique IDs for the required V1 connector families, and constrains the health summary to `connector_id`, `healthy`, and `detail` so credentials or provider-private state are not surfaced accidentally.

## Remaining connector roadmap

F-29 closeout does **not** declare every future connector roadmap item complete. OAuth lifecycle behavior, richer third-party sync, export symmetry, and other C-* capabilities remain governed by `FEATURE_IDEAS.md` / `CONNECTOR_SDK.md` and must be completed in Memory Search order before any Jarvis transition.

No voice, vision, gesture, spatial, hologram, or other Jarvis-specific behavior is part of this milestone.
