# C-07 Podcast RSS Connector — Acceptance Closeout

Status: **candidate complete; merge only after full CI passes on the exact PR head**.

## Canonical acceptance boundary

`FEATURE_IDEAS.md` defines C-07 as **Podcast RSS connector** with acceptance **“Transcript or show notes.”** `CONNECTOR_SDK.md` defines the import mapping as **Feed URL → Episodes → metadata + show notes or transcript API**.

The repository-controlled C-07 boundary is therefore satisfied by deterministic RSS/Atom discovery plus show-note ingestion into the shared connector pipeline. A provider-specific transcript API is not required when usable show notes are present; it remains an optional enhancement rather than a prerequisite for this disjunctive acceptance criterion.

## Implemented behavior

- `PodcastImportService` accepts a public RSS/Atom feed URL, validates it with the shared SSRF guard, disables automatic redirects, revalidates every redirect target, bounds redirects and response bytes, and rejects DTD/entity declarations.
- Feed parsing produces stable episode IDs from GUID, episode URL, audio URL, or a deterministic feed/title/date fallback and drops duplicate episode identities deterministically.
- `podcast.v1` normalizes episode metadata and preserves feed URL, episode URL, GUID, audio URL, publication date, duration, and source identity.
- HTML show notes are cleaned and emitted as evidence segments when no inline transcript text exists.
- Ingest uses the shared `ConnectorIngestService`, forwards the caller's `user_id`, uses the canonical internal `podcast://episode/{external_id}` reference, and requires no mandatory AI call.
- The connector remains read-only; it does not write back to the podcast host or fetch audio autonomously.

## Executable acceptance evidence

`tests/test_podcast_connector.py` proves:

- deterministic GUID-based episode deduplication;
- source provenance and show-note evidence extraction;
- duration normalization;
- private-feed rejection even when fixture XML is supplied;
- DTD/entity rejection; and
- connector-registry availability.

`tests/test_podcast_acceptance.py` additionally locks the shared-pipeline boundary by proving that the same canonical episode identity is preserved across tenants while each ingest call forwards its own tenant `user_id`, connector identity, feed provenance, and show-note payload.

## Explicitly out of scope for C-07 closeout

- downloading or transcribing podcast audio;
- mandatory speech-to-text or LLM processing;
- provider-specific transcript API integrations;
- authenticated/private podcast feeds requiring credentials or billing;
- background polling/subscription behavior; and
- any Jarvis-specific voice, vision, gesture, spatial, hologram, ambient-capture, or hardware work.

Those capabilities require separate source-of-truth promotion and acceptance criteria before implementation.
