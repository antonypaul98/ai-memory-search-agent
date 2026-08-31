# AI Memory Agent

> **Search everything you saved — even when you no longer remember the title, source, or exact words.**

[![CI](https://github.com/antonypaul98/ai-memory-search-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/antonypaul98/ai-memory-search-agent/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Self-hosted](https://img.shields.io/badge/self--hosted-yes-success)](#quick-start)

**AI Memory Agent** is a self-hosted personal memory system for saved **YouTube videos, web pages, PDFs, GitHub repositories, and bookmarks**. It turns fragmented saved content into one searchable knowledge layer with hybrid retrieval, hierarchical memory, grounded answers, citations, privacy controls, and a browser-first capture flow.

**Version 1.9.0** is complete, with production-hardening work implemented. The next product track expands the memory-intelligence layer. See [`MASTER_SPEC.md`](MASTER_SPEC.md) for the canonical inventory.

---

## Why this exists

People save useful content everywhere and then lose it again.

A title may be forgotten. A bookmark folder may have thousands of items. A video may contain the exact idea you need, but normal search only sees its title and description. AI Memory Agent is built around a different question:

> **“Can I retrieve something the way I remember it, instead of the way it was originally named?”**

Example:

```text
Saved months ago:
  YouTube video: "Building Reliable Agent Systems"

What you remember later:
  "that video where someone explained agent retries and tool failures"

AI Memory Agent:
  → searches semantic + lexical evidence
  → narrows through hierarchical memory
  → returns the relevant source
  → can answer with citations back to the saved evidence
```

---

## What makes this different

This is not a thin `embed → vector DB → LLM` wrapper.

| Capability | What the project does |
| --- | --- |
| **AHME retrieval** | Adaptive Hierarchical Memory Engine: capsule → section → evidence |
| **Hybrid search** | Dense embeddings + SQLite FTS5 fused with Reciprocal Rank Fusion |
| **Diversification** | MMR reduces repetitive search results |
| **Grounded answers** | Answers are synthesized from retrieved evidence with citations |
| **LLM optional** | Deterministic synthesis works with `LLM_PROVIDER=none` |
| **Universal ingest** | Different source types normalize into one memory/index path |
| **Semantic cache** | Similar questions can reuse prior retrieval work |
| **Deduplication** | URL/content hashes + near-duplicate handling |
| **Knowledge layer** | Topics, related-memory signals, timeline, learning edges, graph foundation |
| **Privacy-first** | Explicit save, self-hosting, export/delete, tenant-scoped retrieval |
| **Browser workflow** | Chrome extension + PWA workspace instead of CLI-only UX |

---

## Product flow

```mermaid
flowchart LR
    A[YouTube / Web / PDF / GitHub / Bookmarks] --> B[Capture + Connectors]
    B --> C[Normalize]
    C --> D[Chunk + Memory Capsules]
    D --> E[Embeddings]
    E --> F[(ChromaDB)]
    E --> G[(SQLite + FTS5)]
    F --> H[AHME Retrieval]
    G --> H
    H --> I[RRF + MMR]
    I --> J[Grounded Answers + Citations]
    I --> K[Search Results]
    J --> L[Memory Intelligence / Knowledge Graph]
```

### Retrieval path

```text
query
  ↓
semantic cache
  ↓
coarse memory match
  ↓
relevant source / section narrowing
  ↓
vector + lexical evidence retrieval
  ↓
RRF fusion
  ↓
MMR diversification
  ↓
grounded result / cited answer
```

---

## Current capabilities

### Implemented

- **Capture:** active-tab save, context-menu save, SSRF-safe web fetch
- **Connectors:** YouTube, web articles, PDF, GitHub public README/metadata, bookmark import
- **Ingest:** extraction → normalization → chunking → embeddings → vector + FTS + universal memory
- **Retrieval:** AHME hierarchical search, flat fallback, RRF fusion, MMR diversification, semantic cache, deduplication
- **Ask / RAG:** grounded answers with citations; optional LLM providers; deterministic synthesis without an LLM
- **Memory intelligence:** topics, learning graph, timeline, roadmaps, duplicates, creators, explainable retrieve
- **Knowledge graph:** entity/relation foundation and APIs
- **Jobs:** background playlist/import ingest with pause, resume, retry, cancel
- **Workspace:** searchable PWA with Ask Memory, imports, playlists, dashboard, privacy controls
- **Chrome extension:** Observe + Save, command bar, deep links into the Workspace
- **Auth/privacy:** optional sessions, user-scoped retrieval, export/delete, rate limits, hosted privacy page
- **Trust/lifecycle:** memory state machine + trust scoring foundation
- **Operations:** Docker, CI, benchmark smoke, metrics, liveness/readiness probes, migration/backfill tooling

### Planned

- richer ontology engine
- broader consensus / gap intelligence
- expanded autonomous orchestration
- Watch Later import through Google OAuth
- full connector SDK marketplace
- enterprise-scale multi-tenant deployment

Out of scope for V1: covert recording, keylogging, password capture, and Incognito support.

---

## Benchmark snapshot

The repository includes a reproducible offline benchmark comparing the flat pipeline with hierarchical AHME. The current checked-in report uses a small seeded test corpus, so these numbers are **engineering smoke measurements, not production-scale claims**.

| Metric | Flat | AHME |
| --- | ---: | ---: |
| Cross-video search median | 2.02 ms | **1.75 ms** |
| Repeated search median | 1.87 ms | **1.27 ms** |
| Chat median | 13.34 ms | **12.70 ms** |
| Storage | **463,012 B** | 537,868 B |

Run it yourself:

```bash
python scripts/benchmark_ahme.py
```

Full methodology and results: [`docs/BENCHMARK_AHME.md`](docs/BENCHMARK_AHME.md)

---

## Quick start

Requires **Python 3.11**.

```bash
python3.11 -m venv .venv_clean
source .venv_clean/bin/activate
pip install -r requirements.txt
cp .env.example .env

JOBS_ENABLED=true AUTH_ENABLED=false PWA_ENABLED=true \
  uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open:

| Surface | URL |
| --- | --- |
| Workspace | `http://localhost:8000/` |
| Swagger API | `http://localhost:8000/docs` |
| Liveness | `http://localhost:8000/api/v1/live` |
| Readiness | `http://localhost:8000/api/v1/ready` |
| Metrics | `http://localhost:8000/api/v1/metrics` |
| Privacy | `http://localhost:8000/privacy` |

### Chrome extension

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Choose **Load unpacked**
4. Select `extension/`
5. Set the API base to `http://127.0.0.1:8000/api/v1`
6. Open a supported page or YouTube video and save it to memory

More: [`extension/README.md`](extension/README.md)

---

## Try the core workflow

### Ingest one YouTube item

```bash
python scripts/ingest_item.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

### Search / ask through the app

Start the server, open the Workspace, save a few items, and search using concepts rather than exact titles.

A good demo test is:

1. save two or three videos/articles on related topics
2. search using a phrase that does **not** appear in their titles
3. open **Ask Memory**
4. ask a cross-source question
5. inspect the cited evidence

Recording outline: [`docs/V1_DEMO_SCRIPT.md`](docs/V1_DEMO_SCRIPT.md)

---

## AI / retrieval stack

| Layer | Implementation |
| --- | --- |
| Embeddings | Sentence Transformers (`all-MiniLM-L6-v2`) |
| Vector storage | ChromaDB |
| Lexical retrieval | SQLite FTS5 |
| Fusion | Reciprocal Rank Fusion (RRF) |
| Diversification | Maximal Marginal Relevance (MMR) |
| Hierarchical retrieval | capsule → source → section → evidence |
| Cache | cosine-similarity semantic cache |
| Dedup | hashes + near-duplicate simhash + cross-connector checks |
| Synthesis | optional Ollama / OpenAI-compatible LLM or deterministic mode |
| API | FastAPI |
| Browser | Chrome Manifest V3 extension |
| App | installable PWA |

---

## Repository map

```text
app/
  api/                 FastAPI routes
  services/            ingest, retrieval, chat, intelligence, connectors
  db/                  SQLite / Chroma persistence
  static/              PWA workspace
extension/              Chrome MV3 extension
scripts/                ingest, benchmark, migration, operator tools
docs/                   architecture, release, privacy, operations
MASTER_SPEC.md          canonical product / feature inventory
```

Primary implementation areas:

- `app/services/ingest_service.py`
- `app/services/connector_ingest_service.py`
- `app/services/ahme_engine.py`
- `app/services/search_service.py`
- `app/services/chat_service.py`
- `app/services/sources/*`

---

## Privacy and security

AI Memory Agent is designed around **explicit capture** rather than silent surveillance.

- saved content is user-initiated
- self-hosting is supported
- authenticated retrieval is tenant scoped
- export/delete APIs are available
- SSRF-safe fetching is used for web ingest
- Incognito support is intentionally disabled
- secrets belong in environment configuration, not the repository

See [`docs/V1_PRIVACY_MODEL.md`](docs/V1_PRIVACY_MODEL.md) and [`SECURITY.md`](SECURITY.md).

---

## Testing

```bash
source .venv_clean/bin/activate
pytest -q
```

Benchmark smoke:

```bash
BENCHMARK_RUNS=1 python scripts/benchmark_ahme.py
```

CI runs the test suite plus benchmark smoke on pushes and pull requests.

---

## Contributing

Ideas, bug reports, connector proposals, retrieval experiments, benchmark improvements, and focused pull requests are welcome.

Start with [`CONTRIBUTING.md`](CONTRIBUTING.md). If you are new to the codebase, connector additions and benchmark/test improvements are especially good entry points.

If this project solves a problem you have too, **consider starring the repository** — it helps other people discover it.

---

## Roadmap

| Track | Status |
| --- | --- |
| V1 / V1.9.0 | ✅ Complete |
| Production hardening | ✅ Implemented |
| Memory intelligence expansion | 🚧 Next |
| Broader autonomous orchestration | 📋 Planned |
| Connector ecosystem / marketplace | 📋 Planned |

Canonical execution status: [`MASTER_SPEC.md`](MASTER_SPEC.md)

---

## Documentation

- [`MASTER_SPEC.md`](MASTER_SPEC.md) — canonical feature inventory
- [`KNOWLEDGE_ENGINE.md`](KNOWLEDGE_ENGINE.md) — AHME + knowledge architecture
- [`CONNECTOR_SDK.md`](CONNECTOR_SDK.md) — connector architecture
- [`docs/BENCHMARK_AHME.md`](docs/BENCHMARK_AHME.md) — reproducible benchmark report
- [`docs/OPERATIONS_RUNBOOK.md`](docs/OPERATIONS_RUNBOOK.md) — deploy, health, backup/restore, incident runbook
- [`docs/V1_PRIVACY_MODEL.md`](docs/V1_PRIVACY_MODEL.md) — privacy boundaries
- [`docs/V1_DEMO_SCRIPT.md`](docs/V1_DEMO_SCRIPT.md) — demo recording outline
- [`docs/V1_RELEASE_PLAN.md`](docs/V1_RELEASE_PLAN.md) — release plan

---

## License

MIT — see [`LICENSE`](LICENSE).
