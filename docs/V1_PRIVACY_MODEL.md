# V1 Privacy Model

**Product:** AI Memory Agent (Chrome Extension + Backend)  
**Version:** 1.1  
**Last updated:** 2026-07-30  
**Audience:** Users, Chrome Web Store reviewers, engineering

---

## 1. Privacy Principles

1. **Explicit save beats ambient capture** — Browsing is not permanently stored unless the user saves, imports, or opts into a bounded observation session.
2. **Minimum necessary data** — Collect only fields required for save, search, and display.
3. **User control** — Pause observation, clear temp context, delete memories, export data (V1-8).
4. **Tenant isolation** — Memories scoped by authenticated user.
5. **No secrets in client** — OAuth tokens and API keys live server-side only.
6. **Grounded honesty** — Never claim knowledge that was not indexed.

---

## 2. Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│  Chrome Extension (user device)                                  │
│  ┌──────────────┐   session only    ┌─────────────────────────┐ │
│  │ Content      │ ───────────────► │ chrome.storage.session   │ │
│  │ script       │   title, url,     │ TTL ~30 min (V1-2)       │ │
│  │ (V1-2)       │   yt metadata     │ NOT synced to cloud      │ │
│  └──────────────┘                   └─────────────────────────┘ │
│         │ user clicks Save                                       │
│         ▼                                                        │
│  ┌──────────────┐   HTTPS JSON     ┌─────────────────────────┐ │
│  │ Popup / SW   │ ───────────────► │ Self-hosted or SaaS API  │ │
│  └──────────────┘                   └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  Backend (operator-controlled server)                            │
│  Capture → Ingest → SQLite metadata + Chroma vectors             │
│  Optional LLM (user-configured provider) for synthesis           │
└─────────────────────────────────────────────────────────────────┘
```

**What never flows:**

- Passwords, payment fields, private form inputs
- Keystrokes, screenshots, audio, video recordings
- Incognito tabs (extension not enabled in incognito for V1)
- `chrome://` / browser internal pages

---

## 3. Data Categories

| Category | Examples | Stored? | Where | Retention |
|----------|----------|---------|-------|-----------|
| Temp context | Page title, URL, YT video id | Session only | Extension session storage | Until TTL / clear / browser close |
| Saved memory | Transcript chunks, metadata | Yes | SQLite + ChromaDB | Until user deletes |
| Capture audit | URL, status, error | Yes | SQLite `captures` | Until purge policy |
| Bookmarks import | URL, title, folder path | Yes | SQLite `browser_bookmarks` | Until user deletes |
| Auth | Email hash, session token | If auth on | SQLite `users`, `sessions` | Session TTL 168h default |
| Reflection intent | Goal, save reason | Yes | Video registry | With memory |
| Trust metrics | Scores, tiers | Yes | `memory_records` | With memory |
| Usage telemetry | Search counts per video | Yes | SQLite registry | With memory |

**No third-party analytics in V1** unless explicitly added later with opt-in.

---

## 4. Extension Permissions Justification

| Permission | Required? | Purpose |
|------------|-----------|---------|
| `storage` | Yes | API URL, auth token (sync), user preferences |
| `activeTab` | Yes | Access current tab URL/title on user click |
| `contextMenus` | Yes | "Save to AI Memory" on right-click |
| `bookmarks` | Optional | Folder import only after user grants |
| Host: API origin | Yes | POST capture, search, chat |
| Content scripts `<all_urls>` | V1-2+ | Observe supported pages for temp context |

**V1-1 reduction path:** Narrow content script matches to `*://www.youtube.com/*`, `*://github.com/*`, and article domains incrementally instead of `<all_urls>` where possible.

---

## 5. Backend Security Controls (Existing)

| Control | Implementation |
|---------|------------------|
| SSRF prevention | `validate_public_http_url` blocks private IPs |
| Auth boundary | `get_current_user` on all capture/search routes |
| User scoping | `user_id` on Chroma metadata, jobs, memories; registry composite PK |
| Request size limit | `max_request_body_bytes` |
| Rate limiting | `RateLimitMiddleware` → 429 per client IP (V1-8) |
| Export / delete | `GET /api/v1/privacy/export`, `DELETE /api/v1/memories/{id}`, `DELETE /api/v1/privacy/memories` |
| Session revoke | `POST /api/v1/auth/logout` + Workspace “Log out” |
| CORS | Configurable `cors_origins` includes `chrome-extension://` |
| Secrets | Env vars only (`AUTH_SECRET`, `YOUTUBE_API_KEY`, `OPENAI_API_KEY`) |

---

## 6. Third-Party Services

| Service | Data sent | When | User control |
|---------|-----------|------|--------------|
| YouTube (yt-dlp / Data API) | Video URLs | Ingest | User saved the video |
| YouTube transcript API | Video id | Ingest | Same |
| Optional LLM (Ollama/OpenAI) | Retrieved chunks + question | Chat | Disable `llm_provider=none` |
| GitHub API (V1-6) | Repo ids | User save/import | OAuth consent |

**No data sold.** Self-hosters run without external LLM.

---

## 7. User Controls (V1 Targets)

| Control | V1-0 | V1 target |
|---------|------|-----------|
| Pause context observation | — | V1-2 ✅ |
| Clear temp context | — | V1-2 ✅ |
| Delete a memory | API partial | V1-8 ✅ API + Workspace UI |
| Export all data | Missing | V1-8 ✅ JSON export |
| Disable recommendations | PWA reflection field | Exists |
| Revoke extension access | Chrome settings | Always |
| Logout / revoke session | PWA auth | Exists when auth on (V1-8 logout) |

---

## 8. Chrome Web Store Disclosure (Draft)

**Single purpose:** Save and search personal learning content from the web.

**Data collected:**

- URLs and page titles you explicitly save
- Optional: bookmark URLs you import
- Optional: YouTube playback position at save time
- Account email if you register on the backend

**Data NOT collected:**

- Browsing history beyond active tab at save time
- Passwords, payment info, form autofill
- Incognito activity

**Data use:** Provide save, search, and chat features against your self-hosted or provided backend.

**Data sharing:** None with extension developer; user-chosen backend and optional LLM provider.

---

## 9. Compliance Notes

| Regulation | V1 posture |
|------------|------------|
| GDPR | Export/delete in V1-8; lawful basis = user consent at save |
| CCPA | No sale; deletion on request |
| Chrome Web Store | Limited use policy; accurate permission justification |
| YouTube ToS | User-initiated save; no circumvention of access controls |
| GitHub ToS | OAuth for private/starred; respect rate limits |

---

## 10. Incident Response (Self-Host)

1. Rotate `AUTH_SECRET` and invalidate sessions
2. Revoke compromised OAuth tokens in provider console
3. Purge affected user's Chroma collection + SQLite rows
4. Document in repo SECURITY.md (V1-9) ✅

---

## 11. Open Privacy Gaps

| Gap | Phase | Priority |
|-----|-------|----------|
| Temp context not implemented | V1-2 | ✅ Done |
| No export/delete UI | V1-8 | ✅ Done |
| Sync ingest may block before ack | V1-2 | ✅ Async YouTube save |
| Content script on all URLs | V1-2+ | Narrow matches where possible |
| Privacy policy HTML page | V1-8 | ✅ `/privacy` (CWS package V1-9 ready) |
| Delete-all memories does not purge bookmarks/captures/topics | Post V1-8 debt | P2 (endpoint is memory-scoped by design) |
| In-process rate limiter not multi-worker | Scale-out | P2 |
| SECURITY.md incident runbook polish | V1-9 | ✅ `SECURITY.md` |

See **`docs/V1_8_AUTH_PRIVACY.md`** for implementation notes.
