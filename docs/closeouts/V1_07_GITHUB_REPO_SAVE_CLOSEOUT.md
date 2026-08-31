# V1-07 GitHub Repository Save — Acceptance Closeout

Status: **Complete for the public-repository save boundary**

## Accepted behavior

- A GitHub owner/repository URL is recognized as a GitHub repository in the browser extension instead of being presented only as a generic web page.
- Saving remains an explicit user action. Observation alone never writes a memory.
- The existing `POST /api/v1/capture/url` path remains the single capture entry point; GitHub does not get a parallel ingestion path.
- Non-YouTube capture resolves through the connector registry. GitHub repository URLs resolve to `github.v1` and are indexed through `ConnectorIngestService` into the universal memory/search path.
- Repository identity is canonicalized as `https://github.com/{owner}/{repo}` with external identity `{owner}/{repo}`. Deeper repo URLs still resolve to the containing repository.
- Public repository metadata and README text become evidence for indexed chunks. The connector records source type, connector ID, canonical URL, author/owner, language, topics, repository metadata, and a deterministic content hash.
- Cross-connector duplicate detection runs before indexing and registration, preserving canonical-record and deterministic-dedup behavior.
- The ingest path remains tenant-scoped by authenticated `user_id` and retains the normal provenance/evidence metadata used by Memory Search.
- No GitHub credential is embedded in the extension or repository. Private repositories require authorization and are refused when authorization is absent.
- No new mandatory LLM call is introduced; existing optional enrichment/capsule behavior remains governed by the normal on-demand configuration.

## Regression coverage

- `tests/extension/test_context.mjs`
  - recognizes owner/repository URLs and deeper repository paths;
  - does not misclassify GitHub settings/navigation as repositories;
  - renders the GitHub repository/README evidence label even when an older observer payload reports generic `web`.
- `tests/test_universal_connectors.py::TestGitHubConnector`
  - canonical owner/repo parsing;
  - metadata and README normalization.
- `tests/test_universal_connectors.py::TestConnectorIngest::test_github_injected_ingest`
  - GitHub connector ingestion through universal memory with deterministic test embeddings.

## Explicitly not included in this boundary

- GitHub starred-repository bulk import (`V1-08`). That requires OAuth/account authorization plus preview and explicit confirmation before bulk writes.
- Private-repository ingestion without user-provided authorization.
- Autonomous repository monitoring, ambient capture, or background browsing-history collection.
- Jarvis-specific voice, vision, gesture, spatial, holographic, or hardware behavior.

Those remain separate work and must not be inferred from this closeout.
