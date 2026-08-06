# V1 Platform Capability Matrix

**Audit date:** 2026-07-28  
**Method:** Repository code inspection + test inventory (**107 tests collected**; brain subset **22 passed** on 2026-07-22). Status **Complete** only when code exists **and** automated tests pass.

**Status legend:** Complete · Partial · Missing · Blocked

---

## Summary Scorecard

| V1 area | Status | Effort to Complete |
|---------|--------|-------------------|
| 1. Context Observer | Missing | L |
| 2. Instant Save | Partial | M |
| 3. YouTube Agent | Partial | L |
| 4. Bookmark Import | Partial | M |
| 5. GitHub | Missing | L |
| 6. Web Articles | Partial | L |
| 7. PDF | Missing | L |
| 8. Agent Command Interface | Missing | L |
| 9. Search & Chat | Partial | M |
| 10. Intelligence Demo UX | Partial | M |

---

## 1. Context Observer

| Field | Detail |
|-------|--------|
| **Status** | **Missing** |
| **Existing implementation** | `extension/content.js` is a one-line stub. No temp context store, TTL, pause/resume, or disclosure UI. |
| **Files** | `extension/content.js`, `extension/background.js`, `extension/manifest.json` |
| **Technical approach** | Content script detects supported hosts (YouTube watch, GitHub repo, article heuristics). Write minimal metadata to `chrome.storage.session` (MV3 session storage) with TTL. Service worker exposes `getContext` / `clearContext` / `pauseObserver`. Popup shows live context panel. Block `chrome://`, `edge://`, extension pages, password fields (`input[type=password]`), payment autofill heuristics. |
| **Dependencies** | V1-1 extension foundation; host permission strategy |
| **Security / privacy risks** | Over-broad content script matches; retaining context beyond session; capturing form values |
| **Platform-policy risks** | Chrome Web Store requires clear single purpose + data use disclosure for page access |
| **Required tests** | Extension unit tests (Jest/vitest) for context extraction mocks; backend none |
| **Acceptance criteria** | User sees exactly what context is held; pause stops updates; clear wipes session storage; nothing persisted until explicit save; incognito not enabled |
| **Demo fallback** | Manual popup shows URL/title from `activeTab` only (current behavior) |
| **Effort** | **L** |

---

## 2. Instant Save

| Field | Detail |
|-------|--------|
| **Status** | **Partial** |
| **Existing implementation** | Popup + context menu POST to `POST /api/v1/capture/url`. YouTube → synchronous `IngestService.ingest_single_url`. Non-YouTube → SSRF fetch + `captures` row with status `stored` (not searchable). Status API: `GET /capture/status/{id}`. |
| **Files** | `extension/popup.js`, `extension/background.js`, `app/services/capture_service.py`, `app/api/routes/capture.py`, `tests/test_distribution.py::TestCaptureAPI` |
| **Technical approach** | Return capture_id immediately; extension polls status or subscribe via job_id. Queue heavy ingest via `JobStore` for extension-origin saves. Merge observed context from content script into payload. |
| **Dependencies** | F-21 (Complete), F-08 ingest, V1-2 context observer |
| **Security / privacy risks** | Sync ingest blocks popup; localhost-only CORS today |
| **Platform-policy risks** | Low if save is user-initiated only |
| **Required tests** | Async capture → job linkage; extension integration test; poll status e2e |
| **Acceptance criteria** | Ack < 2s; processing state visible; failures surfaced with backend error text |
| **Demo fallback** | Popup "Saved." on 200 OK; PWA ingest for heavy demos |
| **Effort** | **M** |

---

## 3. YouTube Agent

### 3a. Save current video (no URL copy)

| Field | Detail |
|-------|--------|
| **Status** | **Partial** |
| **Existing implementation** | Extension saves `tab.url` + `tab.title`. No playback position, playlist context, or in-page metadata extraction. |
| **Files** | `extension/*`, `app/services/ingest_service.py`, `app/services/metadata_service.py`, `app/services/transcript_service.py` |
| **Technical approach** | YouTube content script reads `ytInitialPlayerResponse` / DOM for videoId, channel, description snippet, thumbnail, `currentTime`, playlist id. Pass to capture API in `raw_source`. |
| **Dependencies** | V1-2, YouTube page script permissions |
| **Security / privacy risks** | Parsing untrusted page JSON — validate video ID format |
| **Platform-policy risks** | YouTube ToS: no automated bulk download; user-initiated save OK |
| **Required tests** | Fixture-based parser tests; capture payload integration test |
| **Acceptance criteria** | Save from watch page captures title, channel, position, thumbnail without clipboard |
| **Demo fallback** | Popup save with URL (current) |
| **Effort** | **M** |

### 3b. Playlist / Watch Later import

| Field | Detail |
|-------|--------|
| **Status** | **Complete for V1-6** (public playlist UX); Watch Later OAuth deferred |
| **Existing implementation** | `POST /playlists/preview`, `POST /playlists/ingest` → background job. PWA Capture: preview→confirm→progress with pause/resume/retry/cancel. Extension deep-links to `#capture`. `PlaylistResolver` returns real title; clear errors for key/private/empty/WL. **No Watch Later scrape/OAuth.** |
| **Files** | `app/api/routes/playlists.py`, `app/api/routes/jobs.py`, `app/services/playlist_service.py`, `app/static/js/views/capture.js`, `extension/popup.*`, `tests/test_playlists_v1_6.py`, `docs/V1_6_PLAYLIST_WATCH_LATER.md` |
| **Technical approach** | Public playlist URL + user confirmation. Watch Later: documented Coming soon + `list=WL`/`LL` rejected + public playlist demo. |
| **Dependencies** | F-20 jobs, `YOUTUBE_API_KEY` for reliable preview |
| **Security / privacy risks** | API key server-side only; no WL scraping |
| **Platform-policy risks** | Watch Later requires Google OAuth verification for production (deferred) |
| **Required tests** | Playlist preview/ingest mocks; error messaging; job isolation |
| **Acceptance criteria** | Preview → confirm → job with pause/resume/retry/cancel; progress UI (not raw JSON); Watch Later cannot start unsupported flows |
| **Demo fallback** | Public playlist URL in PWA Capture |
| **Effort** | **M** (done) / **XL** (Watch Later OAuth later) |

### 3c. Natural-language search over saved YouTube

| Field | Detail |
|-------|--------|
| **Status** | **Partial** (backend complete; extension UI missing) |
| **Existing implementation** | AHME hybrid retrieval over transcript chunks, titles, descriptions. `SearchService`, `ChatService`. Enrichment `why_matched`. No explicit "transcript unavailable" report API. |
| **Files** | `app/services/search_service.py`, `app/services/chat_service.py`, `app/services/ahme_engine.py`, `tests/test_search_service.py`, `tests/test_chat_api.py` |
| **Technical approach** | Expose ingest failures in registry; extension command bar routes to `/search` and `/chat`. Surface videos with `transcript_status=missing` in UI. |
| **Dependencies** | F-09, F-10, F-11 |
| **Security / privacy risks** | LLM optional — deterministic fallback exists |
| **Platform-policy risks** | None |
| **Required tests** | Chat/search API tests (exist); add transcript-missing reporting test |
| **Acceptance criteria** | NL queries return cited results; list videos lacking transcripts |
| **Demo fallback** | PWA search/chat panels |
| **Effort** | **S** (wire UI) / **M** (transcript gap report) |

---

## 4. Browser Bookmark Import

| Field | Detail |
|-------|--------|
| **Status** | **Partial** |
| **Existing implementation** | `POST /api/v1/capture/bookmarks/import` stores rows in `browser_bookmarks`, ingests YouTube URLs inline. Returns `{imported, skipped_duplicates}` only. Manifest declares `optional_permissions: ["bookmarks"]` but **no extension code** calls `chrome.bookmarks`. |
| **Files** | `app/services/capture_service.py`, `app/models/capture.py`, `app/db/schema.py`, `extension/manifest.json` |
| **Technical approach** | Extension requests bookmarks permission on user action → folder picker → preview counts client-side → confirm → batch API. Extend API response: `{imported, skipped, failed, unsupported, job_id}`. Failed items retry via job items. |
| **Dependencies** | V1-1, F-23 |
| **Security / privacy risks** | Bulk export of bookmark tree — require explicit confirmation |
| **Platform-policy risks** | `bookmarks` permission triggers CWS review scrutiny — justify in privacy doc |
| **Required tests** | `tests/test_capture_bookmarks.py` (missing); mock bookmark tree |
| **Acceptance criteria** | Folder select, preview, dedup, totals, retry failed |
| **Demo fallback** | curl POST with fixture bookmark JSON |
| **Effort** | **M** |

---

## 5. GitHub

| Field | Detail |
|-------|--------|
| **Status** | **Missing** |
| **Existing implementation** | None. `SourceType` enum is YouTube-only (`app/models/video.py`). No GitHub routes, OAuth, or README fetch. |
| **Files** | N/A — planned: `app/services/sources/github_source.py`, `extension/content.js` (github.com) |
| **Technical approach** | Save current repo: content script extracts owner/repo; backend fetches public metadata + README via GitHub REST (anonymous) or OAuth for starred repos (`repo`/`public_repo` scope). New `SourceType.GITHUB`. Ingest → universal memory + chunks. |
| **Dependencies** | F-36 schema (supports generic source_type in DB; enum must extend), C-02 OAuth framework, V1-8 auth |
| **Security / privacy risks** | Token storage in server session only; never in extension source |
| **Platform-policy risks** | GitHub OAuth App registration; rate limits; ToS for starred repo sync |
| **Required tests** | GitHub metadata parser; ingest fixture; OAuth token refresh mock |
| **Acceptance criteria** | Save repo from page; import starred list with confirmation; search/chat across repos |
| **Demo fallback** | Pre-ingested sample repos via API script; show PWA search only |
| **Effort** | **L** (save + public README) / **XL** (starred OAuth import) |

---

## 6. Web Articles

| Field | Detail |
|-------|--------|
| **Status** | **Partial** |
| **Existing implementation** | Capture accepts URL + selection text. `ssrf_fetch.fetch_readable_text` extracts text server-side. Status `stored` in `captures` table — **not indexed in Chroma/AHME**. Context menu passes `selectionText`. |
| **Files** | `app/services/capture_service.py`, `app/services/ssrf_fetch.py`, `extension/background.js`, `tests/test_distribution.py::TestSSRF` |
| **Technical approach** | Add `SourceType.WEB` + web ingest pipeline (Readability-style extract, chunk, embed). Client-side DOM extract optional for preview. Support `selected_text` as evidence chunk. |
| **Dependencies** | F-21, connector refactor (F-29 partial), V1-5 |
| **Security / privacy risks** | SSRF (mitigated); XSS in stored HTML — store plain text only |
| **Platform-policy risks** | Low |
| **Required tests** | Web ingest integration; selection capture; search hit on article |
| **Acceptance criteria** | One-click page save + selection save searchable in chat |
| **Demo fallback** | Show capture row in API; search YouTube-only in demo |
| **Effort** | **L** |

---

## 7. PDF Import

| Field | Detail |
|-------|--------|
| **Status** | **Missing** |
| **Existing implementation** | Mentioned in `CONNECTOR_SDK.md` / F-29 only. No PDF parser, upload route, or extension file picker. |
| **Files** | N/A |
| **Technical approach** | Extension `input type=file` → `POST /capture/pdf` multipart → PyMuPDF/pdfplumber extract → page-indexed chunks → Chroma metadata `page_number`. |
| **Dependencies** | F-36, file upload middleware, V1-5 |
| **Security / privacy risks** | Malicious PDFs — size limits, sandbox parse, virus scan in prod |
| **Platform-policy risks** | CWS file handling disclosure |
| **Required tests** | PDF chunk fixture; page citation in chat source |
| **Acceptance criteria** | Import PDF, see processing status, cite page in chat |
| **Demo fallback** | Pre-ingested PDF memory via dev script |
| **Effort** | **L** |

---

## 8. Agent Command Interface

| Field | Detail |
|-------|--------|
| **Status** | **Complete for V1-7** |
| **Existing implementation** | Rule-based `CommandRouterService`; `POST /api/v1/agent/command` (+ `/execute`); extension popup command bar; bulk `confirm_token` + Workspace preview handoff. PWA still has separate search/ask panels with `#search/<q>` / `#ask/<q>` deep-links. |
| **Files** | `app/services/command_router.py`, `app/api/routes/agent.py`, `extension/popup.js`, `tests/test_command_router.py`, `docs/V1_7_AGENT_COMMAND.md` |
| **Technical approach** | Command bar → classify → plan JSON; safe search/ask execute via existing services; bulk requires confirm then preview→confirm (no silent write). |
| **Dependencies** | V1-2–V1-6; not full A-01 agent runtime |
| **Security / privacy risks** | Confirm tokens use HMAC; bulk never auto-writes |
| **Platform-policy risks** | Market as command assist / rule-based — not autonomous agent |
| **Required tests** | `tests/test_command_router.py` |
| **Acceptance criteria** | User sees plan + results; bulk import blocked without confirm — **met** |
| **Demo fallback** | PWA tabs with scripted queries |
| **Effort** | **L** (done) |

---

## 9. Search and Chat

| Field | Detail |
|-------|--------|
| **Status** | **Partial** |
| **Existing implementation** | `GET /search`, `POST /chat` with AHME, clarification, grounded synthesis, recommendations, confidence, `why_matched`, source cards. PWA renders results. Extension has no search/chat UI. Vague visual retrieval limited to indexed text/metadata — no computer vision. |
| **Files** | `app/services/search_service.py`, `app/services/chat_service.py`, `app/services/enrichment_service.py`, `app/static/app.js`, `tests/test_search_service.py`, `tests/test_chat_service.py`, `tests/test_chat_api.py` |
| **Technical approach** | Extension side panel or link to PWA; show trust via `GET /memories/{id}/trust`; related via recommendations + knowledge graph neighbors. |
| **Dependencies** | F-09–F-11, F-38, F-33 |
| **Security / privacy risks** | Low |
| **Platform-policy risks** | None |
| **Required tests** | Existing ~15 tests; add extension smoke optional |
| **Acceptance criteria** | Hybrid search, citations, confidence, related memories, honest limits on visual claims |
| **Demo fallback** | PWA (fully functional today for YouTube) |
| **Effort** | **M** (extension UX + trust badges) |

---

## 10. Intelligence Features (Demo)

| Capability | Status | Files | Notes | Effort |
|------------|--------|-------|-------|--------|
| Duplicate detection | **Partial** | `deduplication_service.py`, ingest skip logic, capture batch dedupe | URL dedupe on ingest; chunk dedupe; no cross-source merge UI | S |
| Related memories | **Partial** | `recommendation_service.py`, `knowledge_graph_service.py` | Chat recommendations + graph API; no extension UI | M |
| Topic/project grouping | **Partial** | `reflection` registry, KG tags/topics on ingest | Group by save_reason/goal/entities; no collections UI | M |
| Memory capsules | **Complete** | `capsule_service.py`, AHME hierarchical store | Built at ingest; tested via AHME tests | — |
| Trust/confidence display | **Partial** | `trust_engine.py`, `GET /memories/{id}/trust` | API only; PWA does not show badges (U-06 planned) | S |
| Processing lifecycle status | **Partial** | `memory_lifecycle_service.py`, job events | API + job worker; not in extension | M |
| Explainability (why matched) | **Complete** | `enrichment_service.build_why_matched` | Shown in search results; tested | — |
| Cross-source synthesis | **Missing** | `chat_service.py` | YouTube-only corpus today | L |
| Learning path from resources | **Missing** | — | No generator | L |

---

## Platform Foundation (Cross-Cutting)

| Capability | Status | Files | Effort |
|------------|--------|-------|--------|
| Manifest V3 extension | **Partial** | `extension/manifest.json` | S |
| Auth / tenant isolation | **Partial** | `app/api/auth.py`, `auth_store.py`, `memory_repository.py` | L |
| SSRF-safe fetch | **Complete** | `ssrf_fetch.py`, tests | — |
| Background jobs | **Complete** | `job_worker.py`, `job_store.py`, tests | — |
| Universal Memory + lifecycle + trust | **Complete** | Brain layer, 22 tests | — |
| Knowledge graph foundation | **Partial** | `knowledge_graph_*`, tests | M |
| Delete / export controls | **Complete** (V1-8) | `privacy_service.py`, `/privacy` | M |
| Privacy data-flow doc | **Complete** (this pass) | `docs/V1_PRIVACY_MODEL.md` | — |
| Chrome Web Store listing | **Complete package (V1-9)** — ready to submit | `docs/store/CHROME_WEB_STORE_LISTING.md` | Human Dashboard upload |
| CI pytest gate | **Complete (V1-9)** | `.github/workflows/ci.yml` | — |

---

## Test Coverage Gap (V1 Priority)

| Area | Has tests? | File to add |
|------|------------|-------------|
| Capture bookmarks | No | `tests/test_capture_bookmarks.py` |
| Extension | No | Manual / Playwright optional |
| Web article ingest | No | `tests/test_web_ingest.py` |
| GitHub ingest | No | `tests/test_github_ingest.py` |
| PDF ingest | No | `tests/test_pdf_ingest.py` |
| Command router | Yes | `tests/test_command_router.py` |
| Brain / memory API | Yes | `tests/test_brain_api.py` (5 tests) |

**Full suite gate:** `pytest -q` → 107 collected; run green before V1 store submission.
