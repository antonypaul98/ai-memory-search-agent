# V1 Release Plan

**Target:** Shippable AI Memory Agent Chrome extension + public GitHub repo + demo + Chrome Web Store / LinkedIn launch  
**Last updated:** 2026-07-30  
**Canonical phase IDs:** `MASTER_SPEC.md` §0.7  
**Prerequisite audit:** Complete (`docs/V1_PLATFORM_CAPABILITY_MATRIX.md`)

---

## Dependency-Ordered Phases

```
V1-0 Audit ✅ ──► V1-1 Foundation ✅ ──► V1-2 YouTube Agent ✅
                         │
                         ▼
                   V1-3 Intelligence ✅
                         │
                         ▼
                   V1-4 Connectors ✅ ──► V1-5 Workspace ✅
                         │
                         ▼
                   V1-6 Playlist / Watch Later ✅
                         │
                         ▼
                   V1-7 Command / store prep ──► V1-8 Auth ──► V1-9 Demo/Store ✅
```

---

## V1-0 — Release Audit ✅

**Goal:** Truthful inventory; no product code changes.

| Deliverable | Status |
|-------------|--------|
| `docs/V1_PRODUCT_SPEC.md` | Done |
| `docs/V1_PLATFORM_CAPABILITY_MATRIX.md` | Done |
| `docs/V1_EXTENSION_ARCHITECTURE.md` | Done |
| `docs/V1_PRIVACY_MODEL.md` | Done |
| `docs/V1_DEMO_SCRIPT.md` | Done |
| `docs/V1_RELEASE_PLAN.md` | Done |
| `MASTER_SPEC.md` V1 gate | Done |
| `FEATURE_IDEAS.md` V1 section | Done |
| Test inventory (107 collected) | Done |

**Exit criteria:** Stakeholders agree scope; no feature marked Complete without tests.

---

## V1-1 — AI Memory Agent Foundation ✅

**Goal:** Extension feels like an AI assistant that already understands the current page.

| Work item | Status |
|-----------|--------|
| Context Observer (YouTube + web, session TTL, pause/resume/clear) | ✅ |
| Agent Popup (observing UI, never empty) | ✅ |
| Instant Save + stage polling (queued→processing→embedding→completed/failed) | ✅ |
| Health Dashboard + Memory Status + Permissions | ✅ |
| Settings (backend URL, theme, privacy, notifications, debug) | ✅ |
| `GET /api/v1/agent/status`, async capture, retry, schema v5 | ✅ |
| Tests (`test_agent_api`, `test_extension_context`) | ✅ |

**Exit criteria met:** Open YouTube → open extension → see video observed → Save → watch processing → completion. No URL copy.

**Note:** Original “Context Observer” phase label was absorbed into V1-1. **V1-2 is YouTube Memory Agent** (reference connector).

---

## V1-2 — YouTube Memory Agent ✅

**Goal:** Production-quality YouTube connector as the reference implementation for all future connectors.

| Work item | Status |
|-----------|--------|
| `SourceConnector` ABC + `ConnectorRegistry` | ✅ |
| `YouTubeConnector` (yt-dlp + transcript API isolated) | ✅ |
| Validated `YouTubeMemory` model + schema v6 | ✅ |
| Transcript detect/fetch/chunk/embed pipeline | ✅ |
| Fine-grained stages + extension poller | ✅ |
| Hybrid search filters + memory explanation | ✅ |
| Related memories + duplicate detection | ✅ |
| Retry queue, backoff, dead-letter, diagnostics | ✅ |
| Knowledge answers via existing chat (indexed memories only) | ✅ |
| Docs `docs/V1_2_YOUTUBE_AGENT.md` + tests | ✅ |

**Exit criteria met:** Save current YouTube video without URL copy → metadata + transcript pipeline → semantic search with why-matched → grounded answers → related/duplicates → diagnostics.

**Out of scope (deferred):** Playlist import UX, Watch Later OAuth, Memory OS engines — see V1-4+.

---

## V1-3 — Memory Intelligence Layer ✅

**Goal:** Make saved memories feel alive — natural retrieval, explainability, topics, timeline, learning graph, roadmaps, capsules, creator intel, insights.

| Work item | Status |
|-----------|--------|
| Natural retrieve + ExplanationBlock | ✅ |
| Incremental topic discovery (no hardcoded lists) | ✅ |
| Memory timeline modes | ✅ |
| Learning graph with evidence | ✅ |
| Topic roadmap (saved memories only) | ✅ |
| Concept capsules | ✅ |
| Duplicate knowledge + diversity score | ✅ |
| Creator intelligence (observable only) | ✅ |
| Insights dashboard API | ✅ |
| Schema v7 + `docs/V1_3_MEMORY_INTELLIGENCE.md` | ✅ |

**Exit criteria met:** Ask vague memory questions → ranked explained results; browse topics/timeline; roadmap from saved corpus; insights without fabricating content.

---

## V1-4 — Universal Memory Connectors ✅

**Goal:** Bookmarks, web articles, PDFs, and GitHub repos become first-class searchable memories via `SourceConnector`.

| Work item | Status |
|-----------|--------|
| `web.v1` / `pdf.v1` / `github.v1` / `bookmarks.v1` | ✅ |
| `ConnectorIngestService` + cross-dupe index | ✅ |
| ImportManager + health/history APIs | ✅ |
| Capture routes index non-YouTube | ✅ |
| PDF upload + bookmark preview | ✅ |
| Docs `docs/V1_4_UNIVERSAL_CONNECTORS.md` | ✅ |

**Exit criteria met:** Save article/PDF/repo/bookmarks → appears in unified search with source evidence; intelligence hook runs without connector-specific code.

---

## V1-5 — AI Memory Workspace ✅

**Goal:** Cohesive PWA Workspace over existing APIs (no new connectors / engines).

| Work item | Status |
|-----------|--------|
| Dashboard (status, imports, topics, growth, search activity) | ✅ |
| Universal search UI + filters | ✅ |
| Ask Memory (reuse chat + retrieve) | ✅ |
| Memory detail / timeline / topic explorer | ✅ |
| Import manager UI (cancel/resume/health) | ✅ |
| Capture + settings | ✅ |
| Extension deep-link `#ask` | ✅ |
| Docs `docs/V1_5_MEMORY_WORKSPACE.md` + tests | ✅ |
| Post-ship audit remediation (safeHref, cache, cancel, caps) | ✅ |

**Exit criteria met:** Open `/` → understand what’s saved / processing / learned / askable; all views consume live APIs.

---

## V1-6 — YouTube Playlist & Watch Later ✅

**Goal:** Playlist workflows and honest Watch Later fallback on top of the V1-2 connector.  
**Doc:** `docs/V1_6_PLAYLIST_WATCH_LATER.md`

| Work item | Details | Effort | Status |
|-----------|---------|--------|--------|
| Playlist import UX | PWA preview → confirm → progress; reflection/force_refresh; pause/resume/retry/cancel | M | ✅ |
| Playlist API tests | Mocked preview/ingest; clear errors (key/private/empty) | S | ✅ |
| Watch Later | Documented + UI demo fallback — **no scrape**; OAuth deferred | S | ✅ (fallback) |
| Extension connector UI | Bookmarks preview/confirm/import + PDF upload; `#capture` deep-link | M | ✅ |

**Dependencies:** V1-2, V1-4, V1-5  
**Exit criteria met:** Import public playlist from PWA; bookmark/PDF from extension; Watch Later labeled Coming soon with public-playlist demo path.

---

## V1-4 — Bookmark and GitHub Importers

### Bookmarks

| Work item | Effort |
|-----------|--------|
| Request `bookmarks` permission on user click | S |
| Folder tree UI + preview counts | M |
| POST `/capture/bookmarks/import` + extend response totals | M |
| Retry failed via job items | M |
| `tests/test_capture_bookmarks.py` | S |

### GitHub (if scheduled in V1 — may slip to post-V1.0)

| Work item | Effort |
|-----------|--------|
| Extend `SourceType` + schema | S |
| Save current repo (public metadata + README) | L |
| OAuth starred import | XL |
| `tests/test_github_ingest.py` | M |

**Dependencies:** V1-1, F-23  
**Exit criteria:** Bookmark folder import with preview/confirm/totals.

---

## V1-5 — Web and PDF Capture

**Goal:** Searchable non-YouTube memories.

| Work item | Details | Effort |
|-----------|---------|--------|
| `SourceType.WEB`, `SourceType.PDF` | Enum + migration | S |
| Web ingest service | Readability extract → chunk → embed → universal memory | L |
| Selection save | Pass `selected_text` as primary evidence | M |
| PDF upload route | Multipart, page-indexed chunks | L |
| Extension file picker + article save buttons | M |

**Dependencies:** V1-2, F-36, F-29 (partial)  
**Exit criteria:** Saved article appears in search/chat; PDF cite includes page.

---

## V1-7 — Agent Command / Store Prep ✅

**Goal:** Command polish and store packaging prep (not full CWS submission).  
**Status:** Complete — see `docs/V1_7_AGENT_COMMAND.md`.  
**Note:** Playlist work lives in **V1-6** above (`docs/V1_6_PLAYLIST_WATCH_LATER.md`).

| Work item | Effort | Status |
|-----------|--------|--------|
| Extension search/chat / command UX polish | M | ✅ Popup command bar + inline results |
| Confirm patterns for bulk actions | M | ✅ `confirm_token` (HMAC, single-use) + preview handoff |
| Store packaging prep (listing draft, icons) | S | ✅ `docs/store/CHROME_WEB_STORE_LISTING.md` |
| `/api/v1/agent/command` classifier | M | ✅ Rule-based (no LLM agent runtime) |

**Dependencies:** V1-3–V1-6  
**Exit criteria:** Safer command UX; store assets drafted; no full store submission required here. **Met.**

---

## V1-7b — Search, Chat, and Intelligence UX (optional polish)

**Goal:** Demo-visible intelligence polish in extension + PWA (may fold into V1-7 / V1-9).

| Work item | Effort |
|-----------|--------|
| Trust badges on source cards (U-06) | S |
| Lifecycle status chip | S |
| Related memories panel (recommendations + KG) | M |
| Topic grouping by goal/project | M |
| Learning path generator (deterministic from saved list) | L |
| Cross-source synthesis | M |

**Dependencies:** F-10, F-11, F-33, F-38, V1-5  
**Exit criteria:** Demo script steps 4–7 pass in extension or linked PWA.

---

## V1-8 — Authentication, Isolation, Security, and Privacy

**Goal:** Multi-user safe demo; store compliance.  
**Status:** ✅ Complete (2026-07-30) — see `docs/V1_8_AUTH_PRIVACY.md`

| Work item | Effort | Done |
|-----------|--------|------|
| Auth integration test suite (F-19) | M | ✅ |
| Schema tenant hardening (F-31 / P-06 → v9 registry keys) | L | ✅ |
| Delete memory + export JSON API | M | ✅ |
| OAuth adapter stub for Google/GitHub | L | Deferred (C-02 / post-V1) |
| Rate limiting (P-02) | M | ✅ |
| Privacy policy page + CWS disclosure text | S | ✅ |

**Dependencies:** V1-1  
**Exit criteria:** Two users cannot see each other's jobs/memories; export/delete documented. ✅

---

## V1-9 — Demo Polish, GitHub, Chrome Store, and LinkedIn Launch ✅

**Goal:** Demo readiness, GitHub/README polish, CWS listing package, LinkedIn notes, CI.  
**Status:** Complete (2026-07-30) — see `docs/V1_9_DEMO_STORE_LAUNCH.md`.  
**Honesty:** Package is **ready to submit**; live CWS upload + demo video recording + LinkedIn publish are **human steps** (not done from CI).

| Work item | Effort | Status |
|-----------|--------|--------|
| Demo script + `scripts/seed_demo.py` | M | ✅ |
| README + GitHub polish (MIT, topics list, V1 accuracy) | S | ✅ |
| Chrome Web Store listing package + privacy fields | M | ✅ Ready to submit (not auto-uploaded) |
| Store promo assets + screenshot placeholders | S | ✅ (`docs/store/assets/`) |
| LinkedIn launch notes + 2-min clip outline | S | ✅ Copy ready (not published) |
| CI: `pytest -q` on PR (P-05) | S | ✅ `.github/workflows/ci.yml` |
| SECURITY.md + VERSION `1.9.0` | S | ✅ |
| Hosted demo instance (optional Fly/Railway) | L | Deferred (optional; local demo works) |

**Dependencies:** V1-8  
**Exit criteria:** Store package ready (or unlisted publish path documented); public repo polish; demo script works locally. **Met** (human Dashboard upload optional follow-through).

---

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| Watch Later requires Google OAuth verification | Blocks V1 YouTube Agent claim | Demo with public playlist; label "Coming soon" |
| Non-YouTube capture not searchable | Demo gap for articles | Prioritize V1-5 or scope demo to YouTube |
| Sync ingest blocks extension popup | Bad UX | V1-2 async jobs |
| CWS rejects broad host permissions | Launch delay | `optional_host_permissions` + activeTab pattern |
| Test suite runtime (~7–20 min) | Slow CI | `--co` smoke + parallel subset in CI |
| README contradicts MASTER_SPEC | Contributor confusion | V1-9 README rewrite |

---

## Recommended Timeline (Indicative)

| Phase | Duration | Cumulative |
|-------|----------|------------|
| V1-1 | 1 week | 1 w |
| V1-2 | 1–2 weeks | 3 w |
| V1-3 | 1–2 weeks | 5 w |
| V1-4 | 1 week | 6 w |
| V1-5 | 2 weeks | 8 w |
| V1-6 | 1–2 weeks | 10 w |
| V1-7 | 1 week | 11 w |
| V1-8 | 2 weeks | 13 w |
| V1-9 | 1 week | 14 w |

**MVP slice for early demo:** V1-1 ✅ → V1-2 ✅ → V1-3 ✅ → V1-4 ✅ → V1-5 ✅ → V1-6 ✅ playlist/extension connector UX.

---

## V1 track complete

All phases **V1-0 … V1-9** are complete in-repo. Human follow-through (record demo video, CWS Dashboard upload, LinkedIn publish) uses the packages in `docs/store/` and `docs/V1_DEMO_SCRIPT.md`.

**Do not start without an explicit Version 2 gate:** Consensus/Gap engines, multi-agent orchestration, Instagram/Reddit/X/LinkedIn connectors, Watch Later production OAuth, Ontology, enterprise RBAC/MCP/multi-tenancy marketplace.
