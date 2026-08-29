# F-23 Bookmark Import — Closeout Evidence

Status: acceptance-complete pending repository CI and merge.

## Acceptance evidence

F-23's original MASTER_SPEC gap was "no sync UX, no scheduled re-import." Both behaviors now exist in the Memory Search Agent implementation:

- Manual Chrome bookmark import is permission-gated and uses preview -> explicit user confirmation -> import. It does not silently bulk-write bookmarks.
- Scheduled re-import is opt-in in extension settings, requests the optional `bookmarks` permission, and is disabled if permission is absent.
- The MV3 service worker recreates the bookmark-sync alarm on install/startup from saved settings.
- Scheduled imports identify `sync_mode=scheduled`; manual runs remain distinguishable.
- Bookmark snapshots are capped to the backend contract and carry `snapshot_complete=false` when truncated, preventing incomplete snapshots from masquerading as authoritative full snapshots.
- The alarm cadence is normalized deterministically to 1 hour through 168 hours (7 days).

## Regression coverage

`tests/extension/test_bookmarks.mjs` verifies:

- deterministic tree flattening and HTTP(S)-only filtering;
- the 500-item backend request boundary;
- scheduled sync remains disabled without explicit opt-in;
- scheduled sync remains disabled if the optional Chrome permission is absent;
- cadence normalization and bounds;
- oversized snapshots are truncated and marked incomplete.

Full repository CI remains the merge gate.

## Safety / privacy boundaries

- No bookmarks are read on a schedule until the user explicitly enables scheduled sync.
- Enabling scheduled sync requires Chrome's optional bookmarks permission.
- Revoked/missing permission makes scheduling fail closed.
- Manual import retains preview and explicit confirmation before bulk import.
- No credentials are embedded in the repository; existing API/auth settings remain environment/user configured.
- This closes a Memory Search Agent feature only. It does not begin Jarvis voice, vision, gesture, spatial, hologram, or ambient-capture work.
