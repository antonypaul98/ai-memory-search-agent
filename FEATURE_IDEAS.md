# FEATURE IDEAS — AI Memory OS Backlog

**Purpose:** Single backlog of current and future capabilities with prioritization metadata.  
**Status:** Architecture phase — no implementation until assigned in `MASTER_SPEC.md`.  
**Last updated:** 2026-07-28  
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
| F-12 | Answer synthesis | Partial | P1 | M | H | F-16 opt | Deterministic OK; LLM tested |
| F-13 | Clarification | Complete | — | — | M | F-11 | Ambiguity options |
| F-14 | Reflection registry | Complete | — | — | H | SQLite | Persist goal/reason; usage stats |
| F-15 | Enrichment | Complete | — | — | M | F-14 | why_matched, one_line_memory |
| F-16 | LLM provider | Partial | P1 | M | H | external | Integration tests; fallback |
| F-17 | Recommendations | Complete | — | — | M | F-14,10 | Query-based suggestions |
| F-18 | PWA shell | Complete | — | — | H | API | Manifest, SW, UI panels |
| F-19 | Auth & sessions | **Complete (V1)** | P0 | M | H | schema v3 | Demo mode; register/login/logout when enabled |
| F-20 | Jobs & playlists | **Complete** (V1-6 UX) | — | — | H | F-08 | Preview→confirm; pause/resume/retry; PWA progress |
| F-21 | Capture + SSRF | Complete | — | — | H | F-08 | Block private URLs; status API |
| F-22 | Chrome extension | **Complete (V1-1)** | **V1 P0** | M | H | F-21 | Agent popup + observer + async save |
| F-23 | Bookmark import | Partial | **V1 P0** | M | M | F-21, F-22 | Extension folder UI + preview; API totals |
| F-24 | Streamlit UI | Complete | — | — | L | API | HTTP client works |
| F-25 | Docker | Complete | — | — | M | all | Volume persist; healthcheck |
| F-26 | Schema migrations | Complete | — | — | H | SQLite | v3 idempotent |
| F-27 | Benchmark scripts | Partial | P1 | S | L | F-09 | CI smoke benchmark |
| F-28 | CLI tools | Partial | P0 | S | M | F-08 | reset_db + ingest_item working |
| F-29 | Source framework | **Complete** (V1-4) | — | L | H | refactor | YouTube/web/pdf/github/bookmarks connectors registered |
| F-30 | SQLite registry client | Planned | P2 | M | M | F-14 | List/delete without Chroma scan |
| F-31 | User isolation | **Complete (V1)** | P0 | L | H | F-19 | Composite keys; no cross-tenant leak |
| F-32 | Agent system | Missing | P3 | XL | H | F-34,33 | See AGENT_BIBLE.md |
| F-33 | Knowledge graph | **Partial** | P2 | L | H | F-36 | Foundation + APIs + tests; UI → V1-7b / later |
| F-34 | Event bus | Missing | P1 | L | M | — | Domain events + audit |
| F-35 | Distributed queue | Missing | P2 | XL | M | F-34 | Redis workers |

---

## 2. Future Features — Knowledge Engine (see KNOWLEDGE_ENGINE.md)

| ID | Feature | Status | Priority | Difficulty | User Value | Dependencies | Acceptance criteria |
|----|---------|--------|----------|------------|------------|--------------|---------------------|
| N-01 | Consensus Engine | Planned | P2 | L | H | F-09, N-05 | Resolve conflicting claims across sources with cited evidence |
| N-02 | Verification Engine | Partial concept | P1 | M | H | F-12 | Extend `_validate_grounding`; per-claim checks |
| N-03 | Trust Engine | **Partial** (F-38) | P2 | L | H | F-36 | Foundation complete; UI badges → V1-7b / later |
| N-04 | Gap Engine | Planned | P2 | L | H | F-33, F-14 | Detect “you wanted X but never saved Y” |
| N-05 | Knowledge Graph store | Planned | P2 | XL | H | F-29 | Entities + relations queryable |
| N-06 | Reverse Memory | Planned | P2 | M | H | N-04 | “What should I learn next for goal G?” |
| N-07 | Learning Evolution | Planned | P3 | XL | H | N-03, F-34 | Re-rank/re-summarize without full re-ingest |
| N-08 | Cross-source dedup UI | Planned | P2 | M | M | F-09 dedup | Show duplicate memories; merge action |

---

## 3. Future Features — Agents (see AGENT_BIBLE.md)

| ID | Feature | Status | Priority | Difficulty | User Value | Dependencies | Acceptance criteria |
|----|---------|--------|----------|------------|------------|--------------|---------------------|
| A-01 | Agent runtime | Planned | P3 | XL | H | F-34, F-32 | Run agent with tool registry |
| A-02 | Ingest Agent | Planned | P3 | L | H | F-08, F-20 | Monitor URLs; auto-ingest rules |
| A-03 | Research Agent | Planned | P3 | L | H | F-11, N-05 | Multi-hop retrieval + report |
| A-04 | Review Agent | Planned | P3 | M | H | N-04 | Spaced repetition from memories |
| A-05 | Capture Agent | Planned | P2 | M | H | F-21, F-22 | Triage extension queue |
| A-06 | Policy / guardrails | Planned | P3 | L | H | F-19 | Human approval for writes |
| A-07 | Agent audit UI | Planned | P3 | M | M | F-34 | Timeline of agent actions |

---

## 4. Future Features — Connectors (see CONNECTOR_SDK.md)

| ID | Feature | Status | Priority | Difficulty | User Value | Dependencies | Acceptance criteria |
|----|---------|--------|----------|------------|------------|--------------|---------------------|
| C-01 | Connector SDK core | **Complete** (V1-4) | — | L | H | F-29 | Registry + ImportManager + ConnectorIngestService |
| C-02 | OAuth adapter framework | Planned | P2 | L | H | F-19 | Token refresh; scoped secrets |
| C-03 | Web article connector | Planned | P2 | M | H | F-21 | Normalize HTML → memory |
| C-04 | Google Drive connector | Planned | P3 | L | M | C-02 | Docs/PDF ingest |
| C-05 | Notion export connector | Planned | P3 | M | M | C-01 | Import export ZIP |
| C-06 | Readwise bridge | Planned | P2 | M | H | C-01 | Highlight → evidence chunks |
| C-07 | Podcast RSS connector | Planned | P3 | L | M | F-08 pattern | Transcript or show notes |
| C-08 | Export adapter (Markdown) | Planned | P2 | M | M | F-07 | Full memory export |
| C-09 | Share sheet mobile | Planned | P3 | M | H | F-18 | iOS/Android share target |

---

## 5. Future Features — Platform & Ops

| ID | Feature | Status | Priority | Difficulty | User Value | Dependencies | Acceptance criteria |
|----|---------|--------|----------|------------|------------|--------------|---------------------|
| P-01 | Readiness vs liveness probes | Planned | P0 | S | M | GAP-08 | K8s-ready health split |
| P-02 | Rate limiting | **Complete (V1)** | P1 | M | M | F-19 | 429 per user/IP |
| P-03 | Postgres migration | Planned | P2 | XL | M | GAP-02 | Production profile |
| P-04 | Structured metrics (Prometheus) | Planned | P1 | M | L | F-34 | `/metrics` endpoint |
| P-05 | CI pipeline | **Complete (V1-9)** | P0 | S | L | tests | pytest -q on every PR (`.github/workflows/ci.yml`) |
| P-06 | Schema tenant keys | **Complete (v9)** | P0 | L | H | F-31 | Registry composite PK + tests |
| P-07 | Embedding microservice | Planned | P3 | L | M | GAP-08 | Optional remote embed |
| P-08 | Multi-worker safe jobs | Planned | P2 | XL | M | F-35 | No duplicate workers |

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
