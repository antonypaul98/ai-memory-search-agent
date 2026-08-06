# V1-1 Implementation Plan — AI Memory Agent Foundation

**Date:** 2026-07-28  
**Status:** Executing → **Complete** (2026-07-28)  
**Stop after:** V1-1 complete (no V1-3+ features beyond what is listed here)

## Scope (user-defined V1-1)

1. Context Observer (YouTube + generic web, session-only, pause/resume/clear)
2. Agent Popup (alive observing UI)
3. Instant Save (ack + live stages)
4. Health Dashboard
5. Permission Manager
6. Memory Status Widget
7. Settings page

## Affected files

### Backend (new/changed)
- `app/models/agent.py` (new)
- `app/models/capture.py` (stage fields)
- `app/services/agent_status_service.py` (new)
- `app/services/capture_service.py` (async YouTube + stages + retry)
- `app/api/routes/agent.py` (new)
- `app/api/routes/capture.py` (retry endpoint)
- `app/main.py` (register agent router)
- `app/db/schema.py` (v5: search events + capture stage)
- `tests/test_agent_api.py` (new)
- `tests/test_capture_async.py` (new)

### Extension (rewrite)
- `extension/manifest.json`
- `extension/background.js`
- `extension/content.js` → observer
- `extension/shared/*.js` (api, storage, context, permissions)
- `extension/popup.html|css|js`
- `extension/settings.html|css|js`
- `extension/icons/*`
- `extension/README.md`
- `tests/extension/*.mjs` (pure JS unit tests via node)

### Docs
- `MASTER_SPEC.md`, `docs/V1_EXTENSION_ARCHITECTURE.md`, `docs/V1_RELEASE_PLAN.md`

## Risks & mitigations

| Risk | Mitigation |
|------|------------|
| YouTube page structure changes | Multi-source extract (ytInitialPlayerResponse, meta tags, DOM) |
| Sync ingest blocks popup | Async capture + status polling |
| Session storage unavailable | Fall back to `chrome.storage.local` with TTL keys |
| CORS for extension | Existing `chrome-extension://` CORS prefix |
| Over-collection | Restricted URL list; never read password/payment inputs |

## Out of scope
Consensus/Gap engines, multi-agent orchestration, GitHub/PDF/bookmark UI, Watch Later OAuth, command classifier.
