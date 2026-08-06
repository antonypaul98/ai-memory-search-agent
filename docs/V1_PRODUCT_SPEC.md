# V1 Product Spec — AI Memory Agent (Chrome Extension)

**Version:** 1.0  
**Status:** Release discovery complete — implementation gated on V1-1  
**Last updated:** 2026-07-28  
**Scope:** Ship a working Chrome extension + backend demo for GitHub, Chrome Web Store, and LinkedIn. **Frozen:** Consensus Engine, Gap Engine, additional knowledge engines, autonomous multi-agent orchestration, Jarvis-scale architecture.

---

## 1. Product Definition

**V1 is an AI Memory Agent delivered as a Chrome extension** backed by the existing FastAPI intelligence platform (Universal Memory Schema, lifecycle, Trust Engine foundation, knowledge graph foundation, AHME search, chat, ingest, jobs, capture).

| Layer | V1 role |
|-------|---------|
| **Chrome extension** | Primary UX: observe context, instant save, imports, command bar |
| **Companion PWA** | Search, chat, bulk ingest, job monitoring (`app/static/`) |
| **Backend API** | Capture, ingest, memory, search, chat, jobs, auth |

**North star:** A user browses YouTube and the web, saves in one click, and asks natural-language questions across saved knowledge — with explicit privacy controls and no covert surveillance.

---

## 2. V1 Required User Experience (Acceptance Map)

Detailed capability matrix: **`docs/V1_PLATFORM_CAPABILITY_MATRIX.md`**.

| # | Capability | V1 target | Current readiness |
|---|------------|-----------|-------------------|
| 1 | Context Observer | Temp context, pause/clear, disclosure | **Missing** |
| 2 | Instant Save | Ack + async processing state | **Partial** |
| 3 | YouTube Agent | Save w/o URL copy, playlist import, NL search | **Partial** |
| 4 | Bookmark Import | Folder select, preview, dedup, retry | **Partial** (API only) |
| 5 | GitHub | Repo save + starred import | **Missing** |
| 6 | Web Articles | One-click + selection save | **Partial** |
| 7 | PDF | Import, chunk, cite pages | **Missing** |
| 8 | Agent Command Interface | Classify commands, confirm bulk | **Complete (V1-7)** |
| 9 | Search and Chat | Hybrid search, citations, trust, related | **Partial** (backend + PWA; not extension) |
| 10 | Intelligence Demo Features | Dedup, related, topics, capsules, trust UX | **Partial** (backend; limited UX) |

---

## 3. Out of Scope for V1

Aligned with user directive and `MASTER_SPEC.md` §0.5:

- Consensus Engine, Gap Engine, Reverse Memory, Learning Evolution engines
- Autonomous multi-agent orchestration (A-01–A-07)
- Connector SDK marketplace (C-01 full framework)
- Mobile-native apps, voice capture, team wiki
- Covert ambient lifelogging, screenshots, keystroke capture
- Incognito access
- Watch Later via undocumented scraping (must use authorized OAuth or demo fallback)
- Fake OAuth integrations or bypassing platform ToS

Long-term Jarvis docs remain reference only (`JARVIS_VISION.md`, `AGENT_BIBLE.md`).

---

## 4. Architecture Summary

```
Chrome Extension (MV3)
  ├── content scripts → page context (V1-2+)
  ├── service worker → capture, sync, commands
  └── popup / side panel → save, status, command bar

        │ HTTPS + Bearer/cookie auth
        ▼
FastAPI (app/main.py)
  ├── /capture/*     → instant save, bookmarks
  ├── /videos/*      → YouTube ingest
  ├── /playlists/*   → playlist preview/ingest
  ├── /jobs/*        → async processing
  ├── /search, /chat → retrieval + synthesis
  ├── /memories/*    → lifecycle, trust
  └── /knowledge/*   → entities, related

SQLite + ChromaDB + optional LLM
```

Full extension design: **`docs/V1_EXTENSION_ARCHITECTURE.md`**.

---

## 5. Source-of-Truth Contradictions (Resolved for V1)

| Document / artifact | Says | Code reality | V1 resolution |
|---------------------|------|--------------|---------------|
| `README.md` | Phases 3–5 "Pending" (pre-V1-9) | Ingest, search, chat, PWA complete | ✅ README rewritten in V1-9; MASTER_SPEC wins |
| `FEATURE_IDEAS.md` F-33 | "Missing" | KG foundation + APIs + tests exist | Updated to Partial; see matrix |
| `MASTER_SPEC.md` §1.2 | "85 passed" | **107 tests collected** (2026-07-28) | Update baseline on next green full run |
| `extension/README.md` | Bookmark import via extension | No bookmark UI in extension code | V1-4 deliverable |
| `SourceType` enum | YouTube only | Web/GitHub/PDF not in enum | Extend in V1-5/V1-4 |
| Non-YouTube capture | "stored" status | Does **not** enter search index | V1-5 must wire web article ingest |

---

## 6. Demo Success Criteria (V1 Ship Gate)

A reviewer can complete this flow without developer assistance (see **`docs/V1_DEMO_SCRIPT.md`**):

1. Install unpacked extension → connect to running backend
2. On YouTube watch page → save current video without copying URL
3. See immediate acknowledgement → processing completes (or clear failure for missing transcript)
4. Search: *"Find the video about MCP servers"*
5. Chat: *"Summarize what my saved videos say about RAG"* with source cards
6. Import a bookmark folder OR public playlist with preview + confirmation
7. Show trust/lifecycle status for at least one saved memory
8. Pause context observation and clear temp context (when implemented)

---

## 7. Non-Functional Requirements

| Area | Requirement |
|------|-------------|
| Security | MV3, least privilege, SSRF-safe fetch (existing), no secrets in repo |
| Privacy | Temp context TTL, no form/password capture, disclosed observation |
| Policy | Chrome Web Store data-use disclosure; YouTube/GitHub API ToS compliance |
| Performance | Instant save API < 2s ack; heavy ingest async via jobs |
| Reliability | Backend-confirmed success only; visible processing/failure states |
| Tests | No feature marked Complete without code + passing tests |

---

## 8. Related Documents

| Document | Purpose |
|----------|---------|
| `docs/V1_PLATFORM_CAPABILITY_MATRIX.md` | Per-capability audit |
| `docs/V1_RELEASE_PLAN.md` | Phased implementation (V1-0 … V1-9) |
| `docs/V1_EXTENSION_ARCHITECTURE.md` | Extension technical design |
| `docs/V1_PRIVACY_MODEL.md` | Data flows and controls |
| `docs/V1_DEMO_SCRIPT.md` | Recorded demo script |
| `MASTER_SPEC.md` | Canonical feature IDs + V1 release gate |
