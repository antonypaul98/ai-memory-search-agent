# AGENT BIBLE — AI Memory OS Agent Architecture

**Purpose:** Define the Memory Search Agent runtime, catalog, safety policy, and remaining orchestration boundaries.  
**Status:** **A-01–A-07 acceptance-complete for the current Memory Search scope; broader autonomous/event-driven orchestration remains future work.**  
**Last updated:** 2026-08-30  
**Prerequisites:** F-19 Auth, F-34 Event Bus, tenant-scoped memory services, explicit confirmation gates for writes.

---

## 1. Agent Design Principles

1. **Memory is sacred** — agents read liberally; write conservatively.
2. **Tools, not prompts** — side effects go through typed services/tools with auditability.
3. **Grounded by default** — factual outputs use tenant-scoped memory evidence.
4. **Human-in-the-loop** — destructive, merge, or external actions require explicit approval.
5. **Composable** — keep agents small and deterministic where possible.
6. **Tenant-isolated** — every run is scoped to the authenticated `user_id`.
7. **On-demand AI** — deterministic behavior remains usable without an LLM.

---

## 2. Agent Runtime — A-01

### Status

**Acceptance complete.** The repository implements `AgentRuntime` and authenticated runtime endpoints in `app/api/routes/agents.py`.

### Runtime contract

- `POST /api/v1/agents/run`
- `GET /api/v1/agents/runs/{run_id}`
- `POST /api/v1/agents/runs/{run_id}/approve`
- authenticated tenant scope is taken from the current user, never from an untrusted cross-tenant override
- approval state is explicit and persisted/auditable
- policy violations fail closed
- LLM use is optional; deterministic agent paths remain available

### Remaining future boundary

A generic multi-step autonomous tool loop, external side-effect marketplace, and event-driven multi-agent orchestrator are not required for current A-01 acceptance and remain future work.

---

## 3. Agent Catalog

### A-02 — Ingest Agent

**Status: acceptance complete.**

Implemented API surface:

- `POST /api/v1/agents/ingest/rules`
- `POST /api/v1/agents/ingest/rules/{rule_id}/approve`
- `POST /api/v1/agents/ingest/rules/{rule_id}/run`

Safety boundary: new rules are inert until explicitly approved; approved rules operate only through existing connector/ingest services and their canonicalization, provenance, deduplication, and SSRF protections.

### A-03 — Research Agent

**Status: acceptance complete.**

Implemented through `ResearchAgent` and `POST /api/v1/agents/research` as bounded, authenticated, read-only research over the user's memory. Results remain evidence-grounded; richer autonomous web research is future work and must use confirmation-gated external access.

### A-04 — Review Agent

**Status: acceptance complete.**

Implemented through `ReviewAgent` and `POST /api/v1/agents/review/queue`. The current contract builds deterministic spaced-review queues from tenant-scoped memory state without requiring AI.

### A-05 — Capture Triage Agent

**Status: acceptance complete.**

Implemented through `CaptureTriageAgent` and `POST /api/v1/agents/capture/triage`. It validates, canonicalizes, and deduplicates capture candidates without silently writing memory. Any ingest remains behind the normal write path and safety checks.

### A-06 — Gap Agent

**Status: acceptance complete.**

Implemented through `GapAgent` and `POST /api/v1/agents/gaps/analyze`. It performs evidence-backed, tenant-scoped gap analysis and is read-only. Scheduled notifications remain a separate future orchestration concern.

### A-07 — Consolidation Agent

**Status: acceptance complete.**

Implemented through `ConsolidationAgent` and `POST /api/v1/agents/consolidation/analyze`. Analysis is read-only. Entity merges require the separate `POST /api/v1/agents/consolidation/approve-merge` action and an explicit confirmation model; no automatic merge is allowed.

### Chat Orchestrator

`ChatService` remains the current deterministic clarify → retrieve → synthesize path. Wrapping it in a generic autonomous orchestrator is optional future work and must not weaken grounding, tenant isolation, or fallback behavior.

---

## 4. Current Safety/Tool Boundary

The implemented Memory Search agent layer reuses existing typed services rather than granting arbitrary raw database or network access.

| Capability | Current rule |
|---|---|
| Search / retrieve | Tenant-scoped, read-only |
| Research | Bounded, evidence-grounded |
| Capture triage | Validation/dedup only; no silent memory write |
| Ingest rules | Explicit rule approval before execution |
| Entity merge | Explicit separate approval action |
| Raw memory/database write | Not exposed as a generic agent tool |
| External network side effects | Not generally available to agents; future use requires policy + confirmation |
| LLM reasoning | Optional/on-demand; deterministic fallback preserved |

---

## 5. Memory Access Matrix

| Agent | Read memory | Read evidence/graph | Write memory | Confirmation boundary |
|---|---|---|---|---|
| Ingest | Yes | Existing-state checks | Via ingest pipeline | Rule approval before execution |
| Research | Yes | Yes | No by default | Future save/external actions require approval |
| Review | Yes | Yes | No core-content writes | Metadata changes must use typed service boundaries |
| Capture Triage | Existing identity/index state | As needed for dedup | No direct write | Ingest is separate |
| Gap | Yes | Yes | No | N/A |
| Consolidation | Yes | Yes | Merge only through merge service | Explicit approval required |

---

## 6. Orchestration Model

### Implemented now

```text
Authenticated request
  → specific bounded agent/service
  → tenant-scoped reads
  → deterministic result or explicit approval state
  → typed write service only when allowed
```

### Future only

```text
Event-driven orchestrator
  → selects multiple agents
  → schedules autonomous follow-ups
  → invokes external side effects
```

That future model is outside the current Memory Search acceptance boundary until explicitly promoted. It must preserve the same provenance, evidence, privacy, deterministic deduplication, confirmation, and audit guarantees.

---

## 7. Policy Tiers

| Tier | Allowed actions |
|---|---|
| `read_only` | Search, retrieve, analyze; no writes |
| `write_memory` | Typed ingest/metadata operations only, subject to feature-specific gates |
| `external` | Future external side effects; explicit approval required |
| `admin` | Destructive/system operations; human-controlled only |

The safest sufficient tier is always preferred.

---

## 8. Failure Modes

| Failure | Required behavior |
|---|---|
| Retrieval unavailable | Use documented deterministic fallback or fail clearly; never fabricate evidence |
| LLM unavailable | Continue with deterministic behavior where supported |
| Policy violation | Fail closed or enter explicit approval state |
| Cross-tenant access attempt | Reject immediately |
| Duplicate ingest candidate | Preserve canonical identity and deterministic deduplication |
| Merge suggestion without approval | Do not mutate graph state |
| External/irreversible action without approval | Do not execute |

---

## 9. Acceptance State

| Item | State |
|---|---|
| A-01 Agent Runtime | **Complete for current Memory Search scope** |
| A-02 Ingest Agent | **Complete for current Memory Search scope** |
| A-03 Research Agent | **Complete for current Memory Search scope** |
| A-04 Review Agent | **Complete for current Memory Search scope** |
| A-05 Capture Triage Agent | **Complete for current Memory Search scope** |
| A-06 Gap Agent | **Complete for current Memory Search scope** |
| A-07 Consolidation Agent | **Complete for current Memory Search scope** |
| Generic autonomous multi-agent orchestration | Future / not required for current acceptance |
| Unattended external side effects | Out of scope without explicit policy promotion |

---

## 10. Related Documents

| Doc | Role |
|---|---|
| `KNOWLEDGE_ENGINE.md` | Evidence, verification, trust, gaps, graph intelligence |
| `CONNECTOR_SDK.md` | Canonical ingest and connector boundaries |
| `FEATURE_IDEAS.md` | Feature/backlog status |
| `MASTER_SPEC.md` | Execution inventory and phase gates |
| `JARVIS_VISION.md` | Future UX north star only after Memory Search completion gate |
