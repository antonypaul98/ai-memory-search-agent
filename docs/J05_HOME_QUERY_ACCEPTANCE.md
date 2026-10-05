# J05: physical-memory query software slice

J04 remains complete. This slice adds `POST /api/v1/jarvis/home` with the existing
Home natural-language request/response contract. It queries saved physical memory
under the authenticated user and timezone; caller-supplied identity is rejected.
It does not open cameras, change consent, ingest frames or add a parallel store.

Acceptance: supported queries preserve observation/source/time/confidence and
available frame/hash/detector provenance; unsupported commands and missing data
remain explicit; malformed/unbounded requests fail validation; cross-tenant
sightings stay inaccessible; ordinary Jarvis digital and voice routes are unchanged.

Yesterday and this-morning last-seen queries now use the existing bounded sighting
lookup, rather than movement history. A single stationary sighting can answer the
question, and the result is the WhereAnswer expected by the HTTP response. Movement
history retains its existing semantics. Local-day/DST boundaries use the authenticated
timezone. No image bytes or public image URLs are added to responses.

J05 is IN PROGRESS, not a cleared gate. This is an independently reviewable software
slice. Real physical Mac-camera acceptance remains PENDING under
`docs/HOME_MAC_ACCEPTANCE.md`; cloud and simulated tests cannot satisfy it.
