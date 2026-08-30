# C-03 Web Article Connector Closeout

Status: acceptance candidate

## Acceptance boundary

`FEATURE_IDEAS.md` defines C-03 as the Web article connector with the acceptance summary **“Normalize HTML → memory.”** `CONNECTOR_SDK.md` further requires connector ingestion to remain security-first, normalized, user-scoped, testable, and compatible with the shared memory pipeline.

## Implemented behavior

The existing `WebConnector` and shared connector ingest pipeline satisfy that boundary without adding a new subsystem:

- `web.v1` accepts public HTTP(S) article URLs and rejects URLs owned by the YouTube, GitHub, and PDF connectors so routing remains deterministic.
- Public URL validation is applied before network access through the shared SSRF guard.
- Article HTML is normalized into `NormalizedItem` metadata plus readable text segments, canonical URL, content hash, extraction metadata, and source identity.
- `ConnectorIngestService` sends that normalized item through the existing tenant-scoped memory pipeline rather than creating a connector-specific memory store.
- Canonical URL/content-hash duplicate detection prevents repeated ingestion while preserving source/provenance metadata.
- No mandatory LLM call is introduced; extraction and deduplication are deterministic.

## Executable evidence

`tests/test_universal_connectors.py` already covers the C-03 acceptance path:

- `TestWebConnector.test_parse_and_extract_offline` proves article HTML is normalized into web-source metadata plus readable segments.
- `TestWebConnector.test_rejects_youtube` protects deterministic connector routing.
- `TestConnectorIngest.test_web_offline_ingest_and_search` proves the normalized web article enters the shared memory ingest path and a repeated canonical article is skipped.
- `TestCrossDuplicates.test_url_and_hash` proves cross-connector canonical URL and content-hash duplicate detection is deterministic and tenant-keyed.

The repository-wide CI gate exercises these tests on every PR.

## Privacy, provenance, and safety notes

This closeout does not weaken any network or privacy boundary. Live article fetches continue through the SSRF-safe public-URL validator and bounded response-size/timeout settings. The connector records canonical source identity and content hashes; it does not export user content, credentials, or private network data. It also does not autonomously fetch unrelated sources or invoke AI.

## Out of scope

This closeout does not claim completion of OAuth connectors, Google Drive, Notion, Readwise, podcasts, mobile share targets, or export adapters. Those remain separate acceptance audits.

## Closeout decision

C-03 may be marked complete once this closeout passes the full repository CI gate. No runtime code change is necessary because the documented acceptance behavior is already implemented and regression-covered.
