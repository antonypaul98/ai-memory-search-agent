# V1 Extension Architecture

**Manifest:** V3 (`extension/manifest.json`) — **version 1.1.0**  
**Last updated:** 2026-07-29  
**Status:** V1-1 UI foundation; V1-5 Workspace is the full PWA surface (`/#ask`, `/#dashboard`, …). Post-audit: safe links, SW never caches `/api/`, router abort on navigate.

---

## Workspace deep-links (V1-5)

| Hash | View |
|------|------|
| `#dashboard` | Status + recent memories/imports |
| `#search` | Universal search |
| `#ask` | Ask Memory (popup “Ask My Memory”; legacy `#chat` redirects) |
| `#timeline` / `#topics` / `#imports` / `#capture` / `#settings` | Intelligence & ops |
| `#memory/{source}:{id}` | Memory detail |

See `docs/V1_5_MEMORY_WORKSPACE.md`. The extension remains capture/observe chrome; the Workspace is presentation over the same APIs. Tokens for the PWA live in page `localStorage`; extension backend URL stays in extension options.

---

## 1. As-Built (V1-1)

```
extension/
├── manifest.json           # MV3, icons, alarms, optional bookmarks/notifications
├── background.js           # Module SW: context store, save, poll, retry
├── content.js              # Context Observer (YouTube + web)
├── popup.html|css|js       # Agent popup
├── settings.html|js        # Options page
├── icons/icon-{16,48,128}.png
├── shared/
│   ├── api.js              # Backend client
│   ├── storage.js          # Settings + session context TTL
│   ├── context.js          # Pure platform helpers
│   └── permissions.js      # Permission manager snapshot
└── README.md
```

### Message flow

```
Content script ──CONTEXT_OBSERVED──► Service worker
                                       │ chrome.storage.session (TTL 30m)
Popup ◄──GET_ACTIVE_CONTEXT────────────┤
Popup ──SAVE_TO_MEMORY─────────────────┤
                                       ▼
                              POST /api/v1/capture/url (async)
                                       │
Popup ──POLL_CAPTURE──────────────────►│ GET /capture/status/{id}
                                       │
Popup ──GET /agent/status─────────────►│ Health + Memory widgets
```

### Privacy guarantees (enforced in code)

- `incognito: not_allowed`
- Restricted URL prefixes never observed
- No password / payment / form field reads
- Temp context only; Memory write only on explicit Save
- Pause / Resume / Clear Temporary Context

---

## 2. Backend contracts used

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/health` | Connection check |
| `GET /api/v1/agent/status` | Health + memory widgets |
| `POST /api/v1/capture/url` | Instant save (returns queued) |
| `GET /api/v1/capture/status/{id}` | Pipeline stages |
| `POST /api/v1/capture/retry/{id}` | Retry failed |

CORS: `allow_origin_regex=chrome-extension://.*`

---

## 3. Design language

UI copy uses **Memory / Agent / Observe / Added to Memory / Ask My Memory** — never “bookmark” or “capture URL” in user-facing strings.

---

## 4. Next (V1-5+)

- Side panel command bar
- Playlist import UI
- Extension bookmark/PDF picker wired to `/capture/bookmarks/*` and `/capture/pdf`
- Narrower content-script match patterns for CWS review
