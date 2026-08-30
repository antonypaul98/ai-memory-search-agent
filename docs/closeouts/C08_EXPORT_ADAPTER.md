# C-08 Export Adapter Acceptance Closeout

Status: **Complete for the repository-defined C-08 acceptance boundary**

## Source-of-truth acceptance

`FEATURE_IDEAS.md` defines C-08 as the Markdown export adapter with the acceptance summary **Full memory export**.

`CONNECTOR_SDK.md` §3.5 defines two executable acceptance criteria:

1. Export includes timestamp URLs and reflection metadata.
2. Export is re-importable via an import adapter with a round-trip test.

The SDK also lists broader target formats (Markdown vault, JSON archive, CSV index) and a planned asynchronous export-job API. Those are architecture targets, not additional checked C-08 acceptance criteria, so they remain future extensions unless promoted into `MASTER_SPEC.md` with explicit acceptance requirements.

## Evidence

The existing authenticated export surface preserves the complete user-scoped export payload, including canonical/source URLs, timestamps, trust/reflection fields, private metadata, and supporting collections.

PR #107 completed the missing round-trip boundary by:

- preserving the human-readable Markdown output;
- embedding a hidden, versioned, URL-safe machine payload containing the complete export object;
- adding a pure `load_export_markdown()` parser that performs no writes;
- bounding Markdown import size;
- rejecting missing, incomplete, corrupt, and unsupported machine payloads;
- adding regression coverage proving export → Markdown → import preserves canonical URLs, reflection/private metadata, supporting collections, and user/export fields.

CI run #682 passed on PR #107 before squash merge as commit `2299babcd6420e0546a64386a792e4c1362ed3fe`.

## Safety and invariants

- Export remains tenant-scoped and authenticated at the API boundary.
- The import adapter is parse-only and cannot mutate memory state.
- Any future restore/write operation must continue through normal tenant isolation, canonical-record resolution, deterministic deduplication, provenance/evidence preservation, and confirmation gates.
- No credentials, provider tokens, or secrets are added to export behavior.
- No mandatory AI call is introduced.

## Explicitly not claimed

This closeout does **not** claim completion of future Markdown-vault packaging, CSV archive delivery, asynchronous export jobs, external object storage, signed download URLs, or other distribution infrastructure. Those require separate promotion/acceptance work if they are made product requirements.

No Jarvis voice, vision, gesture, spatial, holographic, or hardware behavior is part of C-08.
