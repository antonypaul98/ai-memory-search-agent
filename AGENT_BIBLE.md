# AGENT BIBLE — AI Memory OS Agent Architecture

**Purpose:** Define every planned agent — responsibilities, I/O, tools, memory access, orchestration.  
**Status:** Architecture phase — **no agents implemented** (F-32 Missing).  
**Last updated:** 2026-07-18  
**Prerequisite:** F-34 Event Bus, F-19 Auth, N-03 Trust Engine (policy)

---

## 1. Agent Design Principles

1. **Memory is sacred** — agents read liberally; write conservatively.  
2. **Tools, not prompts** — all side effects go through typed tools with audit logs.  
3. **Grounded by default** — agents use AHME retrieval before claiming facts.  
4. **Human-in-the-loop** — destructive or external actions require approval tiers.  
5. **Composable** — agents are small; orchestrator chains them.  
6. **Tenant-isolated** — agents never cross `user_id` boundaries.

---

## 2. Agent Runtime (Planned — A-01)

### 2.1 Purpose

Execute agent runs with tool registry, policy checks, timeouts, and audit trail.

### 2.2 Inputs

| Input | Type | Description |
|-------|------|-------------|
| `agent_id` | string | Registered agent type |
| `task` | string | Natural language objective |
| `context` | object | Optional goal, video_ids, job_id |
| `policy_tier` | enum | `read_only` · `write_memory` · `external` |
| `user_id` | string | From auth |

### 2.3 Outputs

| Output | Type | Description |
|--------|------|-------------|
| `run_id` | string | Audit identifier |
| `status` | enum | `running` · `completed` · `failed` · `awaiting_approval` |
| `result` | object | Agent-specific payload |
| `tool_calls` | array | Audit log of tool invocations |
| `memory_writes` | array | Pending or committed writes |

### 2.4 Tools (runtime-provided)

| Tool | Access | Description |
|------|--------|-------------|
| `log_event` | audit | Append to agent run log |
| `request_approval` | policy | Pause for human confirm |
| `schedule_followup` | jobs | Enqueue future agent run |

### 2.5 Memory access

- Read via AHME `retrieve()` scoped to `user_id`  
- Write only through `memory_write` tool (policy-gated)

### 2.6 API (planned)

- `POST /api/v1/agents/run`  
- `GET /api/v1/agents/runs/{run_id}`  
- `POST /api/v1/agents/runs/{run_id}/approve`

---

## 3. Agent Catalog

### 3.1 Ingest Agent (A-02)

| Field | Detail |
|-------|--------|
| **Purpose** | Automate capture → ingest based on rules (watch folder, RSS, repeated URLs) |
| **Trigger** | Schedule, webhook, connector event |
| **Inputs** | URL list, `force_refresh`, reflection template |
| **Outputs** | Ingest batch results; job_id if large |
| **Tools** | `ingest_url`, `create_playlist_job`, `check_indexed`, `notify_user` |
| **Memory read** | `is_indexed`, registry metadata |
| **Memory write** | Via ingest pipeline only |
| **Policy** | `write_memory` — auto for trusted domains list |
| **Acceptance** | Rule: “Auto-ingest YouTube from channel X” runs without duplicate ingests |

---

### 3.2 Research Agent (A-03)

| Field | Detail |
|-------|--------|
| **Purpose** | Multi-step research over user's memory — report with citations |
| **Trigger** | User chat command or API |
| **Inputs** | Research question, depth (1–3 hops), output format (brief/report) |
| **Outputs** | Markdown report + source list with timestamps |
| **Tools** | `search_memory`, `retrieve_evidence`, `graph_traverse` (future), `synthesize_report` |
| **Memory read** | Full AHME + optional Knowledge Graph |
| **Memory write** | Optional: save report as capture (approval) |
| **Policy** | Default `read_only` |
| **Acceptance** | 3-hop question answered with ≥3 distinct cited sources |

---

### 3.3 Review Agent (A-04)

| Field | Detail |
|-------|--------|
| **Purpose** | Spaced repetition and review scheduling from saved memories |
| **Trigger** | Daily schedule, user opens “Review mode” |
| **Inputs** | Goals, last review dates, feedback history |
| **Outputs** | Review queue: flashcard-style prompts + links to sources |
| **Tools** | `list_memories_by_goal`, `get_usage_stats`, `schedule_review`, `record_review_result` |
| **Memory read** | Capsules, reflection, usage |
| **Memory write** | Updates review metadata only |
| **Policy** | `write_memory` (metadata fields only) |
| **Acceptance** | Surfaces memories not viewed in 14+ days for active goals |

---

### 3.4 Capture Triage Agent (A-05)

| Field | Detail |
|-------|--------|
| **Purpose** | Process extension/share queue — dedupe, tag, route to ingest |
| **Trigger** | Extension batch, bookmark import |
| **Inputs** | Capture queue items |
| **Outputs** | Ingest decisions, skip reasons, merged duplicates |
| **Tools** | `capture_url`, `dedupe_check`, `apply_reflection_template`, `discard_capture` |
| **Memory read** | Existing URLs, content hashes |
| **Memory write** | Via capture → ingest |
| **Policy** | `write_memory` with SSRF checks |
| **Acceptance** | Duplicate URL in queue ingested once; junk URLs rejected with reason |

---

### 3.5 Gap Agent (A-06 variant of N-04)

| Field | Detail |
|-------|--------|
| **Purpose** | Periodic gap analysis → notify user of learning holes |
| **Trigger** | Weekly cron |
| **Inputs** | Active reflection goals |
| **Outputs** | Gap report (see KNOWLEDGE_ENGINE §8) |
| **Tools** | `analyze_gaps`, `reverse_memory_suggest`, `notify_user` |
| **Memory read** | Registry, capsules, failed jobs |
| **Memory write** | None (suggestions only) |
| **Policy** | `read_only` |
| **Acceptance** | Notification per goal with ≥1 actionable gap |

---

### 3.6 Consolidation Agent (A-07)

| Field | Detail |
|-------|--------|
| **Purpose** | Nightly maintenance — entity merge suggestions, stale flags |
| **Trigger** | Off-peak schedule |
| **Inputs** | User memory corpus snapshot |
| **Outputs** | Proposed merges, stale list (user approves) |
| **Tools** | `find_duplicate_entities`, `flag_stale_memory`, `propose_merge` |
| **Memory read** | Graph, registry, trust scores |
| **Memory write** | Only after approval batch |
| **Policy** | `awaiting_approval` for all writes |
| **Acceptance** | No automatic merge without explicit user approve |

---

### 3.7 Chat Orchestrator Agent (implicit today → explicit future)

| Field | Detail |
|-------|--------|
| **Purpose** | Route user questions to clarify → retrieve → synthesize pipeline |
| **Status** | **Partially implemented** as `ChatService` (not agent runtime) |
| **Future** | Wrap as agent with tool trace for audit |
| **Tools** | `clarify`, `search_memory`, `synthesize`, `recommend` |
| **Migration** | Phase 4: extract ChatService steps into agent tools without behavior change |

---

## 4. Tool Registry (Planned)

| Tool name | Agent(s) | Side effect | Approval |
|-----------|----------|-------------|----------|
| `search_memory` | Research, Chat | None | No |
| `retrieve_evidence` | Research, Chat | None | No |
| `ingest_url` | Ingest, Capture | Writes Chroma+SQLite | Domain allowlist |
| `create_playlist_job` | Ingest | Creates job | Yes if >N videos |
| `capture_url` | Capture | Capture record | No |
| `record_feedback` | Review | Updates usage | No |
| `graph_traverse` | Research | None | No |
| `synthesize_report` | Research | None | No |
| `memory_write_raw` | — | **Blocked** | Always deny |
| `external_fetch` | Research | Network | Yes |
| `notify_user` | Gap, Ingest | Push/email | Configurable |

---

## 5. Memory Access Matrix

| Agent | Read capsules | Read evidence | Read graph | Write ingest | Write metadata | Write graph |
|-------|---------------|---------------|------------|--------------|----------------|-------------|
| Ingest | ✓ | ✓ | — | ✓ | ✓ | — |
| Research | ✓ | ✓ | ✓ | optional | — | — |
| Review | ✓ | ✓ | — | — | ✓ | — |
| Capture Triage | ✓ | — | — | ✓ | ✓ | — |
| Gap | ✓ | — | ✓ | — | — | — |
| Consolidation | ✓ | ✓ | ✓ | — | approve | approve |

---

## 6. Orchestration Model

### 6.1 Single-agent run (default)

```
User task → Agent Runtime → [tool loop max N steps] → result
```

### 6.2 Multi-agent pipeline (future)

```
Orchestrator
  → Capture Triage Agent (if queue non-empty)
  → Research Agent (if question complex)
  → Verification pass (N-02)
  → Chat response
```

### 6.3 Event-driven (future)

```
Event: capture.completed
  → Capture Triage Agent (async)

Event: job.failed
  → Ingest Agent (retry policy)

Event: schedule.daily
  → Review Agent + Gap Agent
```

### 6.4 Orchestrator responsibilities

- Select agent by intent classification (reuse QueryRouter patterns)  
- Enforce global timeout and token/cost budget  
- Serialize writes per user (avoid race on same video_id)  
- Emit audit events to Event Bus  

---

## 7. Policy Tiers

| Tier | Allowed actions |
|------|-----------------|
| `read_only` | Search, retrieve, analyze — no writes |
| `write_memory` | Ingest, capture, metadata updates via tools |
| `external` | Network fetch outside capture SSRF rules — approval required |
| `admin` | Job delete, schema migration — human only |

Default for user-triggered chat: **`read_only`**.  
Default for extension capture queue: **`write_memory`** with domain allowlist.

---

## 8. Failure Modes

| Failure | Behavior |
|---------|----------|
| Tool timeout | Retry once; fail run with partial log |
| AHME unavailable | Flat fallback retrieve |
| LLM unavailable | Deterministic synthesis only |
| Policy violation | `awaiting_approval` or hard fail |
| Cross-tenant access attempt | Immediate abort + security event |

---

## 9. Implementation Phases

| Phase | Deliverable |
|-------|-------------|
| 4a | Event Bus + audit log |
| 4b | Agent runtime + `search_memory` / `ingest_url` tools |
| 4c | Research Agent + approval UI |
| 4d | Review + Gap agents |
| 4e | Consolidation Agent + Learning Evolution hooks |

---

## 10. Related Documents

| Doc | Role |
|-----|------|
| `KNOWLEDGE_ENGINE.md` | Retrieval, trust, verification |
| `CONNECTOR_SDK.md` | Ingest Agent inputs |
| `FEATURE_IDEAS.md` | A-01–A-07 backlog IDs |
| `MASTER_SPEC.md` | F-32, F-34 execution gate |
| `JARVIS_VISION.md` | User-facing agent UX |
