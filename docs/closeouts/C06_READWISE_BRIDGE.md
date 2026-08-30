# C-06 Readwise Bridge — Acceptance Closeout Candidate

## Acceptance boundary

`FEATURE_IDEAS.md` defines C-06 as **Readwise bridge** with the acceptance summary **Highlight → evidence chunks**. This closeout covers the repository-controlled CSV export bridge only.

The implementation is accepted when a tenant-provided Readwise CSV can be normalized deterministically into canonical `readwise.v1` memories, with each distinct highlight represented as groundable evidence, while preserving source metadata and avoiding mandatory AI or provider credentials.

## Implemented behavior

- `ReadwiseImportService` parses UTF-8/UTF-8-BOM CSV exports and requires `Highlight` and `Title` columns.
- Rows are grouped deterministically by canonical source URL when available, otherwise by normalized title + author; the resulting stable hash becomes the connector external ID.
- Duplicate identical evidence rows `(highlight, note, location)` are collapsed deterministically before ingest. Tags from duplicate rows are still merged in first-seen order so deduplication does not discard useful metadata.
- Each grouped source is sent through `ConnectorIngestService` under the authenticated `user_id` and `readwise.v1`, retaining the shared canonical-record, tenant-isolation, provenance, indexing, and duplicate protections.
- `ReadwiseConnector` converts each distinct highlight into a manual `TextSegment`; a note, when present, remains attached to that highlight's evidence text.
- Original source URL, highlight count, tags, and locations are retained in normalized metadata. Readwise highlight memories use a distinct canonical identity from a separately saved full web article.
- The CSV bridge is deterministic and requires no LLM call, Readwise API token, OAuth flow, background polling, or external network request.

## Executable evidence

`tests/test_readwise_import.py` covers:

- grouping multiple highlights into source memories;
- tenant ID propagation into the shared ingest service;
- tag and source provenance preservation;
- deterministic collapse of repeated evidence rows without losing tags;
- one evidence segment per distinct highlight, including attached notes;
- connector registration; and
- rejection of malformed exports missing required columns.

The repository-wide CI gate must pass on the exact PR head before this closeout is considered validated or merged.

## Explicitly outside C-06

This acceptance does **not** claim live Readwise API synchronization, OAuth/token acquisition, continuous polling, external provider verification, billing, or production Readwise-account validation. Those require provider credentials and/or external approval and are not necessary for the specified CSV highlight-to-evidence bridge.

## Safety and architecture invariants

C-06 preserves tenant scoping, canonical connector records, deterministic deduplication, evidence/provenance retention, and on-demand/non-AI operation. No secrets or private CSV contents are written to logs or documentation by this closeout.
