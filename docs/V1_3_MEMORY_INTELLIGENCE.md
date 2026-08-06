# V1-3 Memory Intelligence Layer

**Status:** Implemented  
**Last updated:** 2026-07-28  
**Role:** Make saved memories feel like an intelligent memory system — not raw vector search.

---

## 1. Principles

1. **Evidence only** — every relationship, insight, and answer references stored memories.
2. **Incremental** — topics, edges, capsules, and creators update on each successful ingest (no nightly rebuild).
3. **Explainable** — no silent ranking; every retrieve hit includes why / chunks / entities / path.
4. **No fabrication** — missing topics stay missing; roadmaps never invent unwatched content.
5. **Reuse AHME** — natural retrieval wraps existing hybrid search; it does not fork a second engine.

---

## 2. Architecture

```
Ingest (YouTube connector)
  → Capsule + KG + Universal Memory
  → MemoryIntelligenceService.on_memory_indexed()
       ├─ topic_profiles + topic_memory_links
       ├─ learning_edges (explainable)
       ├─ creator_profiles (idempotent aggregates)
       └─ concept_capsules (topic groupings)

Clients
  → GET /api/v1/intelligence/*
       ├─ retrieve (AHME + ExplanationBlock)
       ├─ topics / timeline / learning-graph
       ├─ roadmap / capsules / duplicates
       └─ creators / insights
```

---

## 3. Topic discovery

Topics are **discovered from saved content**, not a hardcoded catalog.

Sources at ingest:

- Capsule `topics[]`
- Capsule entities / tools
- Optional reflection `goal` → `project`

Categories (heuristic classification of discovered names):

`topic` · `technology` · `framework` · `language` · `company` · `product` · `project` · `concept_cluster`

Each topic stores: summary hint, memory count, first/last seen, evidence strings, linked `video_id`s.

---

## 4. Learning graph

Edges live in `learning_edges` with mandatory `evidence` + `evidence_refs`.

| Relation | When created |
|----------|----------------|
| `same_topic` | Shared normalized topics between two saved videos |
| `same_creator` | Same channel, no shared topic yet |
| `explains` | Intro/beginner language on shared topic |
| `expands` | Advanced / “deep dive” language on shared topic |
| `contradicts` | Contrast language (`vs`, `myth`, …) + shared topic |
| `assumes` | Advanced video linked from beginner-tagged peer topic |

Strength ∈ [0,1], reproducible from stored metadata.

---

## 5. Concept capsules

**Concept capsules** (Feature 7) group many videos under one concept (RAG, MCP, Kubernetes, …).

Distinct from per-video hierarchical `MemoryCapsule` used by AHME.

Fields: summary, key memory video IDs, related creators, learning progress (saved memories / total linked).

---

## 6. Timeline

Modes:

- `recently_saved` — by `saved_at` desc  
- `first_learned` — by `saved_at` asc  
- `most_revisited` — views + searches  
- `recently_learned` — viewed first, then recent saves  
- `topic_evolution` — chronological with topic labels  

Optional `topic` filter.

---

## 7. Roadmap generation

`GET /intelligence/roadmap?topic=…` uses **only saved memories** for that topic:

- Beginner / intermediate / advanced via duration + intro/advanced keywords in title/description/capsule  
- Recommended order = level then duration  
- Missing prerequisites = `assumes` evidence topics with zero saved memories  
- Suggested next = next step in recommended order  

Never invents external videos.

---

## 8. Explainability

`GET /intelligence/retrieve` returns `IntelligenceHit` with `ExplanationBlock`:

- why  
- matching transcript chunks  
- matching metadata  
- matched entities  
- confidence  
- alternative matches  
- related memories  
- search path  
- evidence refs  

Existing `GET /search` remains unchanged (backward compatible).

---

## 9. Duplicate knowledge & creators

**Duplicates:** exact/near video duplicates plus shared-topic pairs with a **diversity score** (1 = different explanations, 0 = near-identical).

**Creators:** aggregates from the user’s saved videos only — topic coverage, avg duration (depth proxy), beginner/advanced share, related creators by topic overlap, most watched / most useful from usage counters. No invented subjective ratings.

---

## 10. Insights dashboard

`GET /intelligence/insights`:

- Top topics  
- Most saved concepts  
- Most searched concepts (agent + intelligence search events)  
- Forgotten topics (stale + not recently searched)  
- Learning streak (consecutive save days)  
- Knowledge growth / memory growth time series  

---

## 11. Schema (v7)

| Table | Purpose |
|-------|---------|
| `topic_profiles` | Discovered topics |
| `topic_memory_links` | Topic ↔ video |
| `learning_edges` | Explainable learning relations |
| `concept_capsules` | Concept groupings |
| `creator_profiles` | Creator aggregates |
| `intelligence_events` | save/search events for insights |

---

## 12. APIs

| Method | Path |
|--------|------|
| GET | `/api/v1/intelligence/retrieve` |
| GET | `/api/v1/intelligence/topics` |
| GET | `/api/v1/intelligence/topics/{topic_id}` |
| GET | `/api/v1/intelligence/timeline` |
| GET | `/api/v1/intelligence/learning-graph` |
| GET | `/api/v1/intelligence/roadmap` |
| GET | `/api/v1/intelligence/capsules` |
| GET | `/api/v1/intelligence/capsules/{capsule_id}` |
| GET | `/api/v1/intelligence/duplicates` |
| GET | `/api/v1/intelligence/creators` |
| GET | `/api/v1/intelligence/creators/{creator_id}` |
| GET | `/api/v1/intelligence/insights` |

---

## 13. Out of scope (frozen)

GitHub / PDF / Bookmark connectors · Watch Later OAuth · Memory OS · Consensus Engine · Gap Engine · Autonomous agents.

---

## 14. Extension points

- Register richer entity extractors into `on_memory_indexed`  
- Feed chat answers through `ExplanationBlock` wrappers  
- Surface intelligence widgets in extension / PWA without new backends  
