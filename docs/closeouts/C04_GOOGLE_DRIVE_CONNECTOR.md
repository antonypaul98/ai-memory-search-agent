# C-04 Google Drive Connector — Acceptance Closeout

Status: **validation pending on this PR**

## Canonical requirement

`FEATURE_IDEAS.md` defines C-04 as the Google Drive connector with the acceptance boundary **Docs/PDF ingest** and dependency on the shared OAuth adapter framework (C-02). `CONNECTOR_SDK.md` requires connectors to normalize into shared memory primitives, preserve user/source provenance, remain testable, and isolate OAuth secrets.

## Implemented acceptance behavior

The existing `gdrive.v1` implementation satisfies the Memory Search scope without adding a provider-specific background agent or mandatory AI:

- discovery is authenticated and tenant scoped through the shared OAuth token vault;
- only the minimum Google Drive read-only scope is accepted;
- preview is bounded and deterministically deduplicated by Google Drive file ID;
- Google Docs are exported as plain text;
- PDFs are downloaded with the configured response-size ceiling and parsed with the existing PDF dependency;
- unsupported Drive object types and empty/unextractable files fail closed;
- imported content enters the shared `ConnectorIngestService` using the canonical internal reference `gdrive://file/{file_id}`;
- normalized records preserve Drive file ID, MIME type, modification time, view link, provider checksum, content hash, and extracted evidence text;
- canonical/content hashes remain available to the shared deterministic deduplication path;
- provider authorization/network failures are returned as bounded application errors rather than raw provider responses or credentials;
- no LLM is required for discovery, normalization, or ingestion.

## Automated evidence

`tests/test_gdrive_connector.py` covers:

- connector registration and canonical Drive reference routing;
- provenance and extracted text preservation;
- tenant-scoped token use and deterministic duplicate provider-ID collapse;
- fail-closed missing-scope and expired-token behavior;
- Google Doc extraction routed through the universal connector ingestion path;
- PDF download/extraction routed through the same ingestion path;
- rejection of unsupported Drive content types before ingestion.

`tests/test_gdrive_acceptance.py` adds an explicit C-04 privacy regression proving a provider authorization failure cannot surface access or refresh secrets in the application error.

## External boundary

This closeout does **not** claim that Google OAuth application registration, consent-screen verification, production credentials, billing, or live-account verification has been completed. Those require external account/credential/human approval. C-04 acceptance is the repository-controlled connector behavior using the already accepted C-02 OAuth framework.

## Validation gate

Do not promote C-04 to accepted/merged until full repository CI passes on the exact PR head. No Jarvis-specific voice, vision, gesture, spatial, holographic, ambient-capture, or physical-interface work is part of this closeout.
