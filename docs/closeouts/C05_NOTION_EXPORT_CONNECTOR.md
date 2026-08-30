# C-05 Notion Export Connector — Acceptance Closeout

Status: candidate for completion after full CI passes on this exact branch head.

## Acceptance boundary

C-05 is the repository-controlled Notion export ingestion path. It accepts a user-supplied Notion Markdown export ZIP and converts importable pages into canonical Memory Search connector records through `notion.v1`.

The implementation satisfies the backlog criterion `Import export ZIP` without requiring Notion OAuth, a live Notion workspace, background polling, or mandatory AI.

## Evidence

`app/services/notion_import_service.py`:
- parses Notion ZIP exports entirely in memory and never extracts archive contents to disk;
- rejects unsafe archive paths, invalid ZIPs, empty archives, excessive file counts, oversized individual Markdown pages, and excessive aggregate uncompressed size;
- accepts Markdown/Markdown-compatible pages only;
- derives stable titles, content hashes, export paths, and deterministic external IDs;
- deterministically collapses identical page content before ingestion;
- sorts pages deterministically before preview/import;
- calls the shared `ConnectorIngestService` with the authenticated tenant ID, `notion.v1`, preserved export provenance, and the canonical content hash;
- uses no LLM or autonomous network call.

`app/services/sources/notion_connector.py` preserves imported Markdown as groundable transcript evidence and carries export metadata into the canonical connector item.

`tests/test_notion_import.py` proves:
- nested Markdown parsing and provenance preservation;
- tenant-scoped import through the registered connector;
- groundable evidence retention;
- deterministic duplicate collapse;
- ZIP-slip rejection;
- invalid/empty export rejection;
- oversized-page rejection before any ingest write is attempted;
- registry availability of `notion.v1`.

## Safety and product constraints

- No credentials or Notion API tokens are needed for this offline export path.
- No archive member is written to the host filesystem.
- The connector does not invent provenance; the original export path and content hash are retained as evidence inputs.
- Deterministic deduplication happens before writes and the shared ingestion path supplies the repository's canonical-record and tenant-isolation behavior.
- No AI call is required to parse or ingest the export.

## Explicitly outside C-05

The C-05 backlog item specifies Notion **export ZIP** import. Live Notion OAuth/API synchronization, workspace polling, billing, provider verification, or provider-side credentials are separate features and are not claimed here.

## Completion rule

Mark C-05 complete only after the full repository CI gate passes on the exact PR head containing this closeout and its regression coverage.
