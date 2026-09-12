# Agent Context Stack — External Repositories We Intentionally Reuse

**Purpose:** Track how this project benefits from four public agent/code-intelligence repositories without adding unnecessary runtime dependencies or violating license boundaries.

**Reference projects**

1. `trailhq/Graft` (historically reachable from `NanoNets/Graft`) — MIT
2. `DeusData/codebase-memory-mcp` — MIT
3. `msitarzewski/agency-agents` — MIT
4. `calesthio/OpenMontage` — AGPLv3

This document separates **development-time integration**, **patterns we can internalize**, and **code we should not copy**.

---

## 1. Graft — readable repository context graph

### What we want from it

Graft builds a codebase context graph that coding agents can use instead of repeatedly rediscovering the same repository structure. Its useful ideas for us are:

- cached subsystem/concept maps
- linked context nodes instead of full-repository prompt dumps
- targeted pull-context for coding agents
- automatic freshness checks against the working tree
- agent integrations that keep the context layer optional
- local/regenerable context artifacts rather than product data

### How we use it

**Development-time only.** On machines where Graft is installed, use it before broad manual exploration of this repo. The product must still build and run with Graft absent.

Recommended local workflow:

```bash
# Inspect what would change first
npx @nanonets/graft init --dry-run

# Then initialize the agent integration you actually use
npx @nanonets/graft init
```

Do not commit Graft's generated local graph cache unless its upstream workflow explicitly requires a small shared wiring file. Generated context is disposable.

### Internal pattern worth keeping

For our own Memory OS, the analogous product pattern is **progressive context disclosure**: retrieve the smallest high-signal memory neighborhood first, then expand only when the question requires it.

---

## 2. codebase-memory-mcp — deterministic structural code intelligence

### What we want from it

This project indexes source into a persistent structural graph using tree-sitter plus language-server semantics. Its most valuable development uses for us are:

- architecture overview before editing
- symbol/call-chain tracing
- route and service-boundary discovery
- change-impact analysis
- dead-code detection
- cross-service relationship mapping
- targeted semantic/structural search
- architecture-decision memory
- local processing rather than uploading private code to a hosted indexer

### How we use it

**Development-time only unless separately approved.** Prefer it as structural truth; use Graft as the readable orientation layer.

Operational rule:

```text
CBM answers “what is connected to what?”
Graft answers “what does this subsystem mean?”
Native file reads answer “what exact code must change?”
```

Do not enable aggressive auto-indexing over arbitrary parent folders. Scope indexing to the repository being worked on and watch resource usage.

### Internal product ideas worth keeping

These map directly to our Memory OS roadmap:

- deterministic graph construction before LLM reasoning
- relationship queries as first-class tools
- change/impact maps for evolving memories
- explicit architectural decision records
- local-first processing where privacy requires it

---

## 3. Agency Agents — specialist role library

### What we want from it

The repository contains a large catalog of specialized AI roles. We do **not** need hundreds of always-active agents. We want its role separation and deliverable-oriented prompts.

### Selected roles for this project

| Role | Use in our workflow |
|---|---|
| Software Architect | subsystem boundaries and long-term evolution |
| Multi-Agent Systems Architect | agent topology, governance, recovery |
| RAG Pipeline Engineer | chunking, retrieval, reranking, evals |
| Search Relevance Engineer | query intent, ranking, relevance metrics |
| Knowledge Graph Engineer | entities, relationships, provenance |
| Privacy Engineer | PII, retention, deletion, tenant isolation |
| Backend Architect | APIs, persistence, reliability |
| Code Reviewer | correctness/security review |
| Minimal Change Engineer | smallest safe implementation diff |
| DevOps/SRE | deployment, observability, recovery |

### Routing rule

Use at most the smallest useful set of specialists for a task. Example:

```text
retrieval-quality regression
  -> Search Relevance Engineer
  -> RAG Pipeline Engineer
  -> Code Reviewer
```

```text
new autonomous agent action
  -> Multi-Agent Systems Architect
  -> Privacy Engineer (if user data/external actions involved)
  -> Backend Architect
  -> Code Reviewer
```

The value is **specialization + explicit deliverables**, not personality theater or agent count.

---

## 4. OpenMontage — pipeline/skill/tool architecture patterns

OpenMontage is AGPLv3, so this section is deliberately about **independent architectural inspiration**, not source reuse.

### Patterns we should internalize independently

#### 4.1 Task -> pipeline selection

Do not let the orchestrator improvise an arbitrary tool sequence. Classify the task and choose an explicit pipeline.

For Memory OS:

```text
capture URL
  -> preflight
  -> fetch
  -> normalize
  -> dedupe
  -> extract
  -> chunk
  -> index
  -> verify
  -> publish ingest result
```

```text
answer memory question
  -> classify query
  -> retrieve candidates
  -> rerank
  -> gather evidence
  -> contradiction check
  -> synthesize
  -> citation verification
  -> answer
```

#### 4.2 Capability envelope

Maintain a machine-readable answer to:

- Which connectors are configured?
- Which parsers/transcript providers are available?
- Which models/providers are available?
- Which tools are local vs networked?
- Which actions require approval?
- What is the current cost/latency/privacy envelope?

Agents must choose only from real capabilities.

#### 4.3 Tool registry

Every tool should declare at least:

```text
name
purpose
input schema
output schema
side effects
network requirement
cost class
privacy class
approval tier
timeout/retry policy
```

This extends the product's planned typed tool registry in `AGENT_BIBLE.md`.

#### 4.4 Stage contracts

Every pipeline stage gets:

```text
preconditions
inputs
outputs
acceptance checks
retry/fallback behavior
provenance emitted
```

This makes long agent runs resumable and testable.

#### 4.5 Approval gates

Pause before:

- destructive deletion
- bulk memory rewrite/merge
- external posting or messaging
- high-cost provider usage over budget
- privacy-sensitive export
- irreversible schema/data migration

#### 4.6 Provider/tool scoring

When several providers can do the same job, score them against dimensions that matter for the task, for example:

```text
quality
latency
cost
privacy/locality
reliability
context limit/capability fit
availability
```

Prefer deterministic/local tools when they satisfy the acceptance criteria.

#### 4.7 Live run board / replayable audit

OpenMontage's visible pipeline board suggests a strong Memory OS feature: an agent-run timeline that shows what happened without exposing hidden reasoning.

For each run, store user-safe events such as:

```text
query classified
sources retrieved
reranker selected N items
contradiction detected
approval requested
external tool called
memory write proposed/committed
verification passed/failed
```

This can later power a Jarvis-style activity view and debugging/replay system.

#### 4.8 Preflight + self-review

Before execution, verify prerequisites. After execution, validate the promised output rather than trusting successful tool return codes.

Examples:

- ingest: content exists, metadata normalized, chunks indexed, source URL preserved
- answer: citations resolve, evidence supports claims, no cross-tenant source leakage
- agent write: policy allows it, audit record exists, write is idempotent

---

## 5. Combined development workflow

Use the four references together without turning them into four runtime dependencies:

```text
Task arrives
  |
  +--> CBM: structural map / impact / call chain
  |
  +--> Graft: subsystem meaning / compact context
  |
  +--> Specialist role(s): choose the right engineering lens
  |
  +--> Pipeline contract: preflight -> implement -> verify
  |
  +--> Minimal-change review + tests
```

This is the default workflow for substantive changes in this repository.

---

## 6. Adoption checklist for the Memory OS

### Development tooling

- [ ] Use CBM for structural queries when available
- [ ] Use Graft for compact repo orientation when available
- [x] Add repository-level `AGENTS.md` operating rules
- [ ] Add project-specific specialist skill files only where they improve repeatability
- [ ] Benchmark whether the context stack actually reduces tool calls/tokens on this repo

### Product architecture

- [ ] Add capability-envelope API/model
- [ ] Extend typed tool registry with cost/privacy/approval metadata
- [ ] Represent agent workflows as explicit pipeline/stage contracts
- [ ] Add run-event timeline and replay-safe audit model
- [ ] Add preflight checks and post-run verifier hooks
- [ ] Add provider/tool selection scoring with deterministic fallback
- [ ] Add contradiction-aware retrieval and provenance checks where missing

### Governance

- [x] Keep external tooling optional
- [x] Keep AGPL source out of the codebase unless licensing is intentionally changed
- [x] Prefer simplest sufficient solution over framework accumulation
- [ ] Reassess external repositories periodically for maintenance/security changes

---

## 7. License boundary

- **MIT references:** Graft, codebase-memory-mcp, agency-agents. We can reuse/adapt code or prompts subject to MIT notice requirements.
- **AGPLv3 reference:** OpenMontage. Do not copy or create a derivative of its source inside this project unless we deliberately accept the corresponding AGPL obligations. Architectural ideas listed above should be implemented independently from our own requirements and existing code.

---

## 8. Success criteria

This stack is successful only if it measurably improves one or more of:

- fewer repository exploration reads/tool calls
- lower coding-agent token usage
- faster change completion
- fewer missed cross-file impacts
- fewer regressions
- clearer provenance/auditability
- safer agent actions

If a component adds more complexity than value, remove it.
