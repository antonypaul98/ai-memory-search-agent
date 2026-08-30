# FEATURE IDEAS — AI Memory OS Backlog

**Purpose:** Single backlog of current and future capabilities with prioritization metadata.  
**Status:** Architecture phase — no implementation until assigned in `MASTER_SPEC.md`.  
**Last updated:** 2026-08-30  
**ID scheme:** Aligns with `MASTER_SPEC.md` (F-XX) plus future IDs (N-XX, V1-XX).

**Priority:** P0 (now) · P1 (next phase) · P2 (later) · P3 (vision)  
**Difficulty:** S (days) · M (weeks) · L (months) · XL (quarter+)  
**User value:** H / M / L

---

## 1. Current Features (Shipped or Partial)

| ID | Feature | Status | Priority | Difficulty | User Value | Dependencies | Acceptance criteria (summary) |
|----|---------|--------|----------|------------|------------|--------------|-------------------------------|
| F-01 | Config & health | Complete | — | — | M | Chroma | Health 200/503; injectable settings |
| F-02 | YouTube URL parsing | Complete | — | — | H | — | Valid URLs normalized |
| F-03 | Metadata fetch | Complete | — | — | H | F-02 | yt-dlp metadata with timeout |
| F-04 | Transcript fetch | Complete | — | — | H | F-02 | Segments or graceful failure |
| F-05 | Chunking | Complete | — | — | H | F-04 | Overlap + timestamps |
| F-06 | Embeddings | Complete | — | — | H | ST model | Batch embed; test reset |
| F-07 | Chroma repository | Complete | — | — | H | F-06 | CRUD, search, health check |
| F-08 | Batch ingest | Complete | — | — | H | F-03–7 | Skip indexed; force refresh; batch limit |
| F-09 | AHME | Complete | — | — | H | F-08 | Hierarchical + flat fallback; cache |
| F-10 | Search API | Complete | — | — | H | F-09/7 | Enriched results; validation |
| F-11 | Chat API | Complete | — | — | H | F-09–13 | Grounded answer + sources |
| F-12 | Answer synthesis | **Complete** | P1 | M | H | F-16 opt | Deterministic grounded synthesis; optional tested LLM path; safe fallback |
| F-13 | Clarification | Complete | — | — | M | F-11 | Ambiguity options |
| F-14 | Reflection registry | Complete | — | — | H | SQLite | Persist goal/reason; usage stats |
| F-15 | Enrichment | Complete | — | — | M | F-14 | why_matched, one_line_memory |
| F-16 | LLM provider | **Complete** | P1 | M | H | external | Optional/on-demand provider integration with deterministic fallback |
| F-17 | Recommendations | Complete | — | — | M | F-14,10 | Query-based suggestions |
| F-18 | PWA shell | Complete | — | — | H | API | Manifest, SW, UI panels |
| F-19 | Auth & sessions | **Complete (V1)** | P0 | M | H | schema v3 | Demo mode; register/login/logout when enabled |
| F-20 | Jobs & playlists | **Complete** (V1-6 UX) | — | — | H | F-08 | Preview→confirm; pause/resume/retry; PWA progress |
| F-21 | Capture + SSRF | Complete | — | — | H | F-08 | Block private URLs; status API |
| F-22 | Chrome extension | **Complete (V1-1)** | **V1 P0** | M | H | F-21 | Agent popup + observer + async save |
| F-23 | Bookmark import | **Complete** | **V1 P0** | M | M | F-21, F-22 | Extension folder UI + preview; opt-in re-import; API totals |
| F-24 | Streamlit UI | Complete | — | — | L | API | HTTP client works |
| F-25 | Docker | Complete | — | — | M | all | Volume persist; healthcheck |
| F-26 | Schema migrations | Complete | — | — | H | SQLite | v3 idempotent |
| F-27 | Benchmark scripts | **Complete** | P1 | S | L | F-09 | Reproducible AHME benchmark + CI smoke gate |
| F-28 | CLI tools | **Complete** | P0 | S | M | F-08 | reset_db + ingest_item validated |
| F-29 | Source framework | **Complete** (V1-4) | — | L | H | refactor | YouTube/web/pdf/github/bookmarks connectors registered |
| F-30 | SQLite registry client | **Complete** | P2 | M | M | F-14 | Tenant-scoped list/delete without Chroma scan |
| F-31 | User isolation | **Complete (V1)** | P0 | L | H | F-19 | Composite keys; no cross-tenant leak |
| F-32 | Agent system | **Complete for A-01–A-07 acceptance** | P3 | XL | H | F-34,33 | Deterministic tenant-scoped agents with approval-gated writes |
| F-33 | Knowledge graph | **Complete for current acceptance** | P2 | L | H | F-36 | Temporal facts, entity APIs, merge review UI, explicit confirm gate |
| F-34 | Event bus | **Complete** | P1 | L | M | — | Durable domain/audit events with correlation + credential redaction |
| F-35 | Distributed queue | **Complete for current acceptance** | P2 | XL | M | F-34 | Redis wake transport + Postgres authoritative job state |

---

## 2. Future Features — Knowledge Engine (see KNOWLEDGE_ENGINE.md)

| ID | Feature | Status | Priority | Difficulty | User Value | Dependencies | Acceptance criteria |
|----|---------|--------|----------|------------|------------|--------------|---------------------|
| N-01 | Consensus Engine | **Complete** | P2 | L | H | F-09, N-05 | Preserve conflicts; cited source-backed agreement weight |
| N-02 | Verification Engine | **Complete** | P1 | M | H | F-12 | Deterministic per-claim evidence verification |
| N-03 | Trust Engine | **Partial** (F-38) | P2 | L | H | F-36 | Foundation complete; UI badges → V1-7b / later |
| N-04 | Gap Engine | **Complete** | P2 | L | H | F-33, F-14 | Ground missing-knowledge findings in observable coverage/diversity/review state |
| N-05 | Knowledge Graph store | Planned | P2 | XL | H | F-29 | Entities + relations queryable |
| N-06 | Reverse Memory | **Complete** | P2 | M | H | N-04 | Grounded next-learning actions from goal gaps |
| N-07 | Learning Evolution | **Complete** | P3 | XL | H | N-03, F-34 | Bounded tenant-local ranking evolution without evidence mutation/re-ingest |
| N-08 | Cross-source dedup UI | Planned | P2 | M | M | F-09 dedup | Show duplicate memories; merge action |

---

## 3. Future Features — Agents (see AGENT_BIBLE.md)

| ID | Feature | Status | Priority | Difficulty | User Value | Dependencies | Acceptance criteria |
|----|---------|--------|----------|------------|------------|--------------|---------------------|
| A-01 | Agent runtime | **Complete** | P3 | XL | H | F-34, F-32 | Deterministic tenant-scoped runtime with tool registry + approval gates |
| A-02 | Ingest Agent | **Complete** | P3 | L | H | F-08, F-20 | Approved deterministic ingest rules + canonical deduplication |
| A-03 | Research Agent | **Complete** | P3 | L | H | F-11, N-05 | Bounded multi-hop retrieval/report with cited saved-memory sources |
| A-04 | Review Agent | **Complete** | P3 | M | H | N-04 | Spaced review queue for stale active-goal memories |
| A-05 | Capture Agent | **Complete** | P2 | M | H | F-21, F-22 | Deterministic queue triage, dedup, tenant checks, unsafe/junk rejection |
| A-06 | Gap Agent | **Complete** | P3 | L | H | N-04, F-19 | Evidence-backed tenant-scoped gap actions with explicit zero-memory handling |
| A-07 | Consolidation Agent | **Complete** | P3 | M | M | F-33, F-34 | Read-only analysis; merge writes require authenticated explicit confirm |

---

## 4. Future Features — Connectors (see CONNECTOR_SDK.md)

| ID | Feature | Status | Priority | Difficulty | User Value | Dependencies | Acceptance criteria |
|----|---------|--------|----------|------------|------------|--------------|---------------------|
| C-01 | Connector SDK core | **Complete** (V1-4) | — | L | H | F-29 | Registry + ImportManager + ConnectorIngestService |
| C-02 | OAuth adapter framework | **Complete** | P2 | L | H | F-19 | Tenant-scoped encrypted tokens; refresh/rotation/revoke; scoped secrets |
| C-03 | Web article connector | **Complete** | P2 | M | H | F-21 | Safe HTML normalization → canonical memory |
| C-04 | Google Drive connector | **Complete for Docs/PDF acceptance** | P3 | L | M | C-02 | Tenant-scoped Docs/PDF ingest with provenance + deterministic dedup |
| C-05 | Notion export connector | **Complete for export-ZIP acceptance** | P3 | M | M | C-01 | Offline ZIP import with path/size safety and deterministic dedup |
| C-06 | Readwise bridge | **Complete** | P2 | M | H | C-01 | Highlights → deduplicated evidence chunks with merged tags |
| C-07 | Podcast RSS connector | **Complete for show-notes acceptance** | P3 | L | M | F-08 pattern | Safe RSS ingest with deterministic episode identity + show-note evidence |
| C-08 | Export adapter (Markdown) | **Complete** | P2 | M | M | F-07 | Full memory export with lossless Markdown round trip |
| C-09 | Share sheet mobile | Planned / deferred | P3 | M | H | F-18 | Native mobile share target remains outside pre-Jarvis scope |

---

## 5. Future Features — Platform & Ops

| ID | Feature | Status | Priority | Difficulty | User Value | Dependencies | Acceptance criteria |
|----|---------|--------|----------|------------|------------|--------------|---------------------|
| P-01 | Readiness vs liveness probes | **Complete** | P0 | S | M | GAP-08 | K8s-ready health split |
| P-02 | Rate limiting | **Complete (V1)** | P1 | M | M | F-19 | 429 per user/IP |
| P-03 | Postgres migration | Planned | P2 | XL | M | GAP-02 | Production-wide Postgres profile |
| P-04 | Structured metrics (Prometheus) | **Complete** | P1 | M | L | F-34 | `/metrics` endpoint |
| P-05 | CI pipeline | **Complete (V1-9)** | P0 | S | L | tests | pytest -q on every PR (`.github/workflows/ci.yml`) |
| P-06 | Schema tenant keys | **Complete (v9)** | P0 | L | H | F-31 | Registry composite PK + tests |
| P-07 | Embedding microservice | Planned | P3 | L | M | GAP-08 | Optional remote embed |
| P-08 | Multi-worker safe jobs | **Complete for current acceptance** | P2 | XL | M | F-35 | Atomic claims/leases; no duplicate workers; unsafe SQLite split-worker mode fails closed |

---

## 6. Future Features — UX (see JARVIS_VISION.md)

| ID | Feature | Status | Priority | Difficulty | User Value | Dependencies | Acceptance criteria |
|----|---------|--------|----------|------------|------------|--------------|---------------------|
| U-01 | Unified command bar | **Partial** (V1-7 extension command) | P2 | M | H | F-18 | Search + chat + capture one input |
| U-02 | Memory timeline view | Planned | P2 | M | H | F-14 | Browse by date/goal |
| U-03 | Proactive daily briefing | Planned | P3 | L | H | A-04, N-04 | Morning digest notification |
| U-04 | Offline ingest queue | Planned | P2 | M | H | F-18 SW | Queue URLs offline; sync later |
| U-05 | Voice capture | Planned | P3 | L | M | C-01 | Speech → memory (spec first) |
| U-06 | Trust badges on results | Partial | P2 | S | H | F-38 | API exists; PWA/extension UI → V1-7b / post-V1 |

---

## 1b. V1 Chrome Extension Release (Active Gate)

**Gate doc:** `MASTER_SPEC.md` §0.7 · **Audit:** `docs/V1_PLATFORM_CAPABILITY_MATRIX.md`

| ID | Capability | Status | Phase | Difficulty | Dependencies |
|----|------------|--------|-------|------------|--------------|
| V1-01 | Context observer | **Complete** (V1-1) | V1-1 | L | F-22 |
| V1-02 | Instant save + async status | **Complete** (V1-1) | V1-1 | M | F-21, F-20 |
| V1-03 | YouTube in-page metadata | **Partial** (V1-1 baseline) | V1-3 | M | V1-02 |
| V1-04 | Playlist import UX | **Complete** (V1-6) | V1-6 | M | F-20 |
| V1-05 | Watch Later OAuth | Deferred (demo fallback) | V1-6/post | XL | C-02, Google verification |
| V1-06 | Bookmark folder import UI | **Complete** (V1-4 APIs + V1-6 extension) | V1-6 | M | F-23, F-22 |
| V1-07 | GitHub repo save | Partial (connector exists) | V1-4 | L | C-02 |
| V1-08 | GitHub starred import | Missing | post-V1 | XL | V1-07, OAuth |
| V1-09 | Web article ingest (searchable) | **Complete** (V1-4) | V1-4 | L | F-21, F-36 |
| V1-10 | PDF import + page cites | **Complete** (V1-4 + V1-6 extension UI) | V1-4/6 | L | F-36 |
| V1-11 | Agent command bar | **Complete** (V1-7) | V1-7 | L | F-10, F-11 |
| V1-12 | Extension search/chat UX | **Complete** (V1-7 command + deep-links) | V1-7 | M | F-18, F-22 |
| V1-13 | Learning path generator | Missing | V1-7b / post-V1 | L | F-09, F-33 |
| V1-14 | Export / delete controls | **Complete** (V1-8) | V1-8 | M | F-19, F-31 |
| V1-15 | Chrome Web Store listing | **Complete package (V1-9)** — ready to submit; not auto-uploaded | V1-9 | M | V1-8 privacy doc |
| V1-16 | Demo video + LinkedIn launch | **Materials complete (V1-9)** — script/seed/LinkedIn copy; video/post are human steps | V1-9 | S | V1-03–V1-12 |

**Frozen for V1:** N-01, N-04, N-06, N-07, A-01–A-07, C-01 marketplace.

**V1 track:** Complete (V1-0 … V1-9). See `docs/V1_9_DEMO_STORE_LAUNCH.md`. Do not start Version 2 without an explicit gate.

---

## 7. Dependency Graph (Backlog)

```
P0 Foundation:  P-05, P-06, F-28, F-31, F-19, P-01
       ↓
P1 Memory Intel: F-16, N-02, F-27, P-02, P-04, F-34
       ↓
P2 Connectors + Graph: C-01–03, C-06, C-08, F-29, N-05, N-03, N-04, F-35, U-01–02
       ↓
P3 Agents + Jarvis: A-01–07, N-01, N-06, N-07, U-03, U-05
```

---

## 8. Prioritization Rubric

| Score | Priority | When to build |
|-------|----------|---------------|
| P0 | Foundation | Blocks production or tenant safety |
| P1 | Memory intelligence | Improves core search/chat trust |
| P2 | Expansion | Connectors, graph, UX depth |
| P3 | Jarvis | Agents, proactive OS behaviors |

**Difficulty calibration (this team / repo):**

- **S:** Single module, tests included, no schema break  
- **M:** Multi-module, may need migration  
- **L:** New subsystem, significant tests + docs  
- **XL:** Infra change, migration, or new runtime (agents, queue)

---

## 9. How to Promote an Idea to Execution

1. Add or update row in this file with acceptance criteria.  
2. Map to `MASTER_SPEC.md` feature ID or add new F-XX / N-XX entry.  
3. Assign phase in MASTER_SPEC roadmap.  
4. **Only then** open implementation PR referencing IDs.

---

## 10. Related Documents

| Document | Contents |
|----------|----------|
| `MASTER_SPEC.md` | Canonical status + phase gates |
| `COMPETITOR_BIBLE.md` | Why features matter competitively |
| `KNOWLEDGE_ENGINE.md` | N-01–N-08 deep spec |
| `AGENT_BIBLE.md` | A-01–A-07 deep spec |
| `CONNECTOR_SDK.md` | C-01–C-09 deep spec |
| `JARVIS_VISION.md` | U-01–U-06 UX north star |
| `docs/V1_PRODUCT_SPEC.md` | V1 scope and ship criteria |
| `docs/V1_RELEASE_PLAN.md` | V1-0 … V1-9 phases |
