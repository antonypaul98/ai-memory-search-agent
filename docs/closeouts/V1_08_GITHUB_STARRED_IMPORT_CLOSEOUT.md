# V1-08 GitHub Starred Import — Acceptance Closeout Candidate

Status: **validation pending on this PR**

## Acceptance boundary

The V1 platform capability matrix requires GitHub starred-repository import to use the shared OAuth framework, show a preview before mutation, require confirmation, and route repositories into searchable Memory with provenance. This closeout covers repository-controlled behavior only; live GitHub OAuth App registration remains an external deployment prerequisite.

## Implemented behavior

- `GET /api/v1/imports/github/starred/preview` reads the current tenant's encrypted `github.v1` OAuth credential from the shared `OAuthTokenVault` and fetches a bounded starred-repository list.
- Preview output contains repository metadata only; access/refresh tokens are never returned.
- Starred repositories are deterministically de-duplicated by case-insensitive `owner/repo` identity and sorted before display/import.
- `POST /api/v1/imports/github/starred` refuses all mutation unless `confirm=true` is explicit.
- Optional selected repositories must exist in the freshly fetched starred set; arbitrary repository injection through the bulk-import endpoint is rejected.
- Confirmed repositories reuse `ConnectorIngestService.ingest_url(..., connector_id="github.v1")`, preserving canonical GitHub owner/repo identity, universal-memory provenance, tenant scoping, evidence/chunk indexing, and deterministic cross-source duplicate handling.
- OAuth token material is passed only ephemerally to the connector when authenticated repository access is required. It is not added to normalized metadata, result payloads, or audit payloads.
- Authenticated README retrieval supports explicitly confirmed private starred repositories when the stored GitHub credential permits access; anonymous public-repository save continues to work unchanged.
- Discovery/import is deterministic and does not require an LLM. Existing optional AI enrichment remains on-demand inside the canonical ingest path.
- Missing, expired, rejected, or rate-limited GitHub credentials fail closed with bounded application errors.

## Automated evidence

`tests/test_github_starred_import.py` locks:

1. deterministic starred-list de-duplication and ordering;
2. preview confirmation signaling and OAuth-secret non-disclosure;
3. refusal to ingest before explicit confirmation;
4. rejection of selected repositories outside the current starred set;
5. canonical `github.v1` ingestion with tenant identity preserved;
6. no OAuth secret in import results;
7. fail-closed missing/expired OAuth credentials;
8. authenticated README evidence retrieval for a private repository without persisting the token.

Existing GitHub connector/universal-memory tests continue to cover repository normalization, evidence ingestion, source provenance, and cross-source search behavior.

## External boundary

This repository cannot create or approve a GitHub OAuth App on the user's behalf without external account ownership and provider approval/credentials. Production use therefore still requires a GitHub OAuth App plus a `github.v1` credential provisioned through the accepted C-02 vault integration. No client secret, access token, refresh token, billing action, or private account data is committed to the repository or required by automated CI.

This external deployment prerequisite does not justify exposing a raw-token API: credentials remain behind the shared encrypted token-vault boundary.

## Validation gate

Do not promote V1-08 to accepted/merged until full repository CI passes on the exact PR head. No Jarvis-specific voice, vision, gesture, spatial, holographic, ambient-capture, or hardware work is part of this closeout.
