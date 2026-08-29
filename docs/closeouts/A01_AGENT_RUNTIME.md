# A-01 Agent Runtime Closeout

## Status

A-01 is implemented and validated as the deterministic, policy-gated Memory Search agent execution substrate. This closeout does **not** start or approve any Jarvis-specific voice, vision, gesture, spatial, holographic, ambient-capture, or hardware work.

## Acceptance evidence

The implemented runtime in `app/services/agent_runtime.py` provides the planned A-01/F-32 foundation:

- durable agent-run and tool-call audit records;
- tenant-scoped run lookup and tool execution using the authenticated `user_id`;
- a bounded typed tool allowlist rather than arbitrary prompt-driven side effects;
- explicit policy tiers and an `awaiting_approval` state for memory-writing tools;
- explicit user approval before a pending memory write can execute;
- raw/unregistered tools are rejected before execution;
- Event Bus audit events for run start, approval wait, approval, tool start, completion, and failure;
- deterministic execution by default; no LLM planner or continuously running AI is required.

The public API already exposes the planned runtime boundary:

- `POST /api/v1/agents/run`
- `GET /api/v1/agents/runs/{run_id}`
- `POST /api/v1/agents/runs/{run_id}/approve`

## Regression coverage

`tests/test_agent_runtime.py` directly verifies:

- read-only search is tenant-scoped;
- write tools cannot execute under read-only policy;
- write-memory runs wait for explicit approval;
- approval executes the same tenant-scoped pending run;
- feedback writes validate types and remain tenant-scoped;
- unknown/raw tools fail closed;
- cross-tenant run lookup is denied;
- runtime events are durably persisted;
- the run/get/approve API contract and HTTP failure behavior.

Additional agent-specific suites (`tests/test_research_agent.py`, `tests/test_review_agent.py`, `tests/test_capture_triage_agent.py`, `tests/test_gap_agent.py`, `tests/test_consolidation_agent.py`) are tracked separately against their own acceptance criteria and are **not** implicitly closed by this milestone.

## Safety and architecture invariants

- Memory remains the authoritative product state; agent execution does not bypass canonical ingest/search services.
- Side effects use typed service boundaries and preserve existing provenance/deduplication behavior.
- Tenant identity is passed through to memory reads and writes; run records are looked up by `(run_id, user_id)`.
- Memory writes require an appropriate policy tier plus explicit approval.
- Optional AI remains on-demand. A-01 is deliberately deterministic and does not require an LLM planner.
- No secrets or provider credentials are written to agent audit payloads by this closeout.

## Scope boundary

This closes the **A-01 agent runtime foundation only**. It does not claim all of F-32/A-02–A-07 complete. Each remaining agent, guardrail, audit-UI, and orchestration acceptance criterion must be independently reconciled against implementation and regression evidence before the Memory Search roadmap can transition to `JARVIS_VISION.md`.
