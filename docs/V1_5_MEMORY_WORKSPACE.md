# V1-5 — AI Memory Workspace

**Status:** Complete (post-audit remediation 2026-07-29)  
**Depends on:** V1-1 … V1-4 (agent status, intelligence, connectors, import manager)

---

## Goal

Expose existing backend capabilities as a cohesive **AI Memory Workspace** (PWA + extension deep-links).

The Workspace is a **presentation and orchestration layer only**. It does not duplicate retrieval, ingest, intelligence, or connector business logic.

---

## Non-goals (explicit)

- Memory OS / Ontology / Activity Memory  
- Browser History, VS Code, Terminal connectors  
- Autonomous agents  
- New connectors  
- New answer / ranking engines  

---

## UI architecture

```
app/static/
  index.html          # Workspace shell + hash nav
  app.js              # Module entry · route mounting · dispose hooks
  style.css           # Tokens + workspace + a11y
  sw.js               # Shell-only cache (never /api/)
  js/
    api.js            # Sole transport · GET cache · abort tags · error scrubbing
    util.js           # Escape, safeHref, SOURCE_TYPES, RENDER_LIMITS, memoryRef
    router.js         # Hash routes · unbind · AbortController per navigation
    views/
      dashboard.js | search.js | ask.js | timeline.js
      topics.js | imports.js | capture.js | settings.js | memory.js
```

### Routes

| Hash | View |
|------|------|
| `#dashboard` | Status, recent memories, queue, topics, growth |
| `#search` | Universal search |
| `#ask` | Ask Memory (`#chat` redirects here) |
| `#timeline` | Chronological intelligence timeline |
| `#topics` | Topic explorer + roadmaps + capsules |
| `#imports` | Import manager |
| `#capture` | Ingest / playlist / bookmarks / PDF |
| `#settings` | Theme, token, privacy, connector health |
| `#memory/{source}:{externalId}` | Memory detail |

**Extension deep-links (consistent with V1-6):**

| Popup action | Opens |
|--------------|-------|
| Ask My Memory | `{pwa_url}#ask` |
| Playlist in Workspace | `{pwa_url}#capture` |

Deep-links navigate only; they do not start playlist ingest or Watch Later import.

### Router lifecycle

- `bindNav` attaches hash + nav listeners once; returns `unbindNav`.
- Each navigation bumps a generation and creates a fresh `AbortController`.
- Leaving capture/timeline disposes poll timers / debounced reloaders.
- `abortInflight(tag)` cancels in-flight tagged fetches.

---

## Backend APIs added or changed for V1-5

| Change | Why necessary | Layer |
|--------|---------------|-------|
| `GET /memories?limit=` → `MemoryStore.list_recent` | Dashboard / today's captures need universal recent list; no duplicate query logic in UI | Store + thin route |
| `POST /imports/{id}/cancel` → `ImportManager.cancel_import` | Import Manager UI cancel; cooperative cancel in `_run_import` | Service (auth via `user_id`) |
| `GET /imports/{id}?item_limit=` | Bound large import item payloads | Service |
| `GET /intelligence/retrieve` + `date_from` / `date_to` | Expose existing `SearchFilters` fields already enforced in `search_service._passes_filters` | Route pass-through only |
| PDF upload magic-byte / type checks | Server-side validation (client checks are UX only) | Route |

These are **not** compensatory engines — they expose operations the Workspace must call that already belonged in ImportManager / MemoryStore / SearchFilters.

---

## Features → APIs reused

| Feature | Primary APIs |
|---------|----------------|
| Dashboard | `/agent/status`, `/intelligence/insights`, `/timeline`, `/topics`, `/memories`, `/imports`, `/connectors/health` |
| Universal search | `/intelligence/retrieve` (+ presentation filters for source/topic/connector) |
| Ask Memory | `POST /chat` + `/intelligence/retrieve` |
| Memory details | `/memories/by-external`, lifecycle, `/youtube/memories/*` when source is youtube |
| Import manager | `/imports*`, `/connectors/health` |
| Timeline / topics | `/intelligence/timeline`, `/topics`, `/roadmap`, `/capsules` |
| Capture | `/videos/ingest`, `/playlists/*`, `/jobs/*`, `/capture/*` |
| Settings | localStorage + `/health`, `/pwa/config`, `/connectors/health` |

---

## Cache behavior

- In-memory GET cache in `api.js` (default TTL 15s).
- Keys: `METHOD:/path?query`.
- `clearApiCache(substring)` deletes keys **containing** the substring (fixed in audit).
- Mutations (ingest, import cancel/resume, PDF, bookmarks) call `clearApiCache`.
- Service worker: network-first for shell; **never** caches `/api/` or requests with `Authorization`; old caches deleted on activate.

---

## Security assumptions

- All memory/user text rendered via `escapeHtml` or `textContent`.
- External links via `safeHref` / `externalLink` (http/https only) + `rel="noopener noreferrer"`.
- Bearer tokens stored in `localStorage` (same-origin PWA); scrubbed from error strings.
- PDF validated server-side (size + `%PDF` magic / content-type).
- Import cancel / memory list scoped by authenticated `user_id`.
- Client-side validation is **not** a security boundary.

---

## Performance

- Parallel dashboard fetches with abort on navigate away.
- Render caps via `RENDER_LIMITS` (search 40, timeline 100, import items 100, etc.).
- Import detail API `item_limit` (default 200).
- No virtual scrolling (list sizes bounded; not justified yet).

---

## Desktop / future reuse

ES modules with no Chrome APIs. Desktop hosts can load the same tree; swap only token storage. Ontology V2 adds new view modules + routes without rewriting existing views.

---

## Known limitations (honest)

1. Intelligence **timeline / roadmap APIs** still expose YouTube-oriented fields (`video_id`); Workspace maps them via `memoryRef` / `hitExternalId` but cannot invent universal timeline rows the API does not return.
2. Related memories API is YouTube-only today.
3. Source/topic/connector filters on search may apply client-side when retrieve lacks those query params (date/language/channel/min_confidence are server-side).
4. `SOURCE_TYPES` icon/label map must gain an entry for brand-new source types (health still works without UI map edits).
5. Not sized for 100k memories in a single unbounded DOM list — APIs + `RENDER_LIMITS` keep the UI safe; full-library browsing needs future pagination UX.
6. No executable frontend coverage tooling in CI (no Node). Backend covered by pytest; JS guarded by static behavioral/security tests.

---

## Architectural audit answers (post-remediation)

1. **Duplicated logic?** No domain engines in JS. Presentation filters only.
2. **50–100 connectors?** Register connectors; UI icons optional in `SOURCE_TYPES`.
3. **Ontology V2?** Additive views/routes.
4. **Desktop reuse?** Yes.
5. **Cancel race?** Cooperative `_is_cancelled` checks in import loop.

---

## Tests

`tests/test_workspace_v1_5.py` — shell, SW rules, safeHref, cache clear, date filters, cancel auth, PDF validation, item limits, a11y CSS markers.
