# AI Memory Search Agent — Coding-Agent Operating Guide

This file defines how coding agents should work in this repository. It complements `AGENT_BIBLE.md`, which describes product/runtime agents. The rules here are for **development agents** (Codex, Claude Code, Cursor, Gemini, etc.).

## 1. Context-first, not file-wandering

Before broad repository exploration, prefer a structural context layer when available:

1. **codebase-memory-mcp** for deterministic AST/LSP-backed architecture, call graph, impact, dead-code, route, and cross-service queries.
2. **Graft** for a human-readable subsystem/concept graph and fast orientation.
3. Native repository search/read tools only for the exact files needed after the structural query narrows scope.

Never make either external tool a hard runtime dependency of the product. If unavailable, fall back to repository-native search.

## 2. Pull context on demand

Keep prompts small. Load only the subsystem, symbols, evidence, and tests needed for the current task. Prefer targeted structural queries over dumping whole files or whole directories into context.

For changes that cross boundaries, explicitly map:

- entry point → service → persistence/external boundary
- callers/callees of changed symbols
- affected tests and contracts
- tenant/auth/security boundaries
- migration/schema consequences

## 3. Specialist development roles

Use focused roles inspired by the MIT-licensed `msitarzewski/agency-agents` project rather than one generic agent doing everything. The default virtual team for this repo is:

- **Software Architect** — boundaries, contracts, evolution
- **Multi-Agent Systems Architect** — orchestration, trust, failure recovery
- **RAG Pipeline Engineer** — chunking, retrieval, reranking, evaluation
- **Search Relevance Engineer** — query understanding, ranking, quality metrics
- **Knowledge Graph Engineer** — entity resolution, graph retrieval, provenance
- **Privacy Engineer** — PII minimization, deletion/retention, tenant isolation
- **Backend Architect** — APIs, data models, reliability
- **Code Reviewer / Minimal Change Engineer** — test-gated review and smallest safe diff

Do not spawn all roles for every task. Route only to roles that materially improve the result.

## 4. Pipeline-driven execution

Borrow the **architecture pattern**, not source code, from OpenMontage:

1. classify the task
2. select the smallest appropriate pipeline
3. run preflight/capability checks
4. execute typed stages
5. stop at explicit approval gates for risky/destructive/external actions
6. verify outputs against acceptance criteria
7. record an auditable run summary

For this product, typical pipelines are:

- connector ingest
- normalization/deduplication
- retrieval/ranking
- answer synthesis + citation verification
- maintenance/consolidation
- agent action execution

Each pipeline should have explicit inputs, outputs, failure behavior, and deterministic fallbacks.

## 5. Capability envelope

Before calling optional models/providers/connectors, determine what is actually available. Never assume a key, model, binary, or provider exists.

Prefer this order:

1. deterministic/local implementation
2. already-configured provider
3. lowest-cost provider meeting quality/latency/privacy constraints
4. stronger provider only when the task requires it

Record why a provider/tool was selected when the choice materially affects cost, privacy, or answer quality.

## 6. Provenance, confidence, and contradiction handling

Every user-facing factual result derived from saved content must preserve source provenance. Ranking/agent decisions should expose enough evidence to audit why an item was selected.

Where confidence is meaningful, store or calculate it from evidence quality rather than inventing a model self-score. Contradictory memories should be surfaced, not silently collapsed.

## 7. Test-gated development

Before merge:

- run focused tests for changed behavior
- run regression tests for affected contracts
- run security/privacy checks when auth, tenant scope, network fetch, or secrets handling changes
- prefer behavior-preserving minimal diffs
- do not merge speculative features that are not tied to an accepted backlog item or current user goal

For larger changes, perform a second-pass review using a different specialist role than the implementer.

## 8. External-source license rule

The four reference projects currently used by this development workflow have different licenses:

- Graft — MIT
- codebase-memory-mcp — MIT
- agency-agents — MIT
- OpenMontage — AGPLv3

MIT-licensed code/prompts may be adapted with required notices preserved where applicable. **Do not copy or derive OpenMontage AGPL source into this repository unless we intentionally accept AGPL obligations.** We may independently implement general architectural ideas such as staged pipelines, capability discovery, approval gates, audit logs, provider scoring, and self-review.

## 9. Product runtime remains independent

These development tools improve how agents understand and modify the repository; they are not automatically part of the shipped memory product. Any external component promoted into runtime must pass separate security, privacy, reliability, licensing, and maintenance review.

## 10. Default principle

Use the simplest sufficient architecture. Reuse proven patterns when they reduce risk or effort, but do not add a framework merely because it is available.
