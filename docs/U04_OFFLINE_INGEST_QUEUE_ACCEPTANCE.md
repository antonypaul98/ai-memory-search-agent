# U-04 Offline Ingest Queue — Acceptance Closeout

## Scope

The Workspace can explicitly queue a public `http(s)` URL while the browser is offline and replay it through the existing canonical `/api/v1/capture/url` ingestion endpoint after connectivity returns.

## Acceptance guarantees

- Offline queueing applies only to the explicit **Capture URL** action; playlists, PDFs, bookmarks, search, chat, and autonomous background capture are not silently queued.
- Queue records are persisted locally in IndexedDB and contain only the normalized URL plus queue timestamp.
- Bearer tokens are never persisted in the offline queue. Authentication is read fresh from the current Workspace session only when replay occurs.
- The queue is bounded to 100 entries and accepts only `http:` / `https:` URLs.
- Replay is deterministic FIFO over the stored records and reuses the normal canonical capture endpoint, preserving the backend's existing SSRF checks, provenance, canonical records, deduplication, tenant isolation, and evidence handling.
- A queued item is deleted only after a successful HTTP response. Authentication, validation, server, or network failures preserve the remaining item(s) for a later retry.
- Reconnect triggers replay on demand in the foreground Workspace; no mandatory AI call or unattended external side effect is introduced.

## Explicit non-goals

- No voice, vision, gesture, spatial/holographic, ambient-capture, or other Jarvis behavior.
- No background scraping or capture of arbitrary browsing activity.
- No offline queuing of credentials, PDFs, bookmark batches, playlist imports, or destructive actions.
- No bypass of backend confirmation gates or privacy controls.

## Regression coverage

`tests/test_offline_capture_ui.py` locks the Workspace wiring, canonical endpoint reuse, reconnect replay path, no-secret-persistence rule, queue bound/protocol restriction, and fail-preserving replay behavior.
