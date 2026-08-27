# Context Router Research — 2026-08-27

**Status:** Active product direction and competitive guardrail.  
**Engineering label:** Context Router. **Do not use “ContextRail” as the product name** — an active AI standards/context platform already uses it. Final branding requires a separate name/trademark/domain scan.  
**Principle:** Do not become another generic vector database, memory API, enterprise search product, prompt compressor, source router, or MCP marketplace. Build the neutral execution layer that decides **which independent context system should win this request, under this user's policy, quality, latency, freshness, token, cost, and residency constraints — and continuously prove that decision with measured performance**.

---

## 1. Market conclusion

The AI memory/context market is real and increasingly crowded. Strong products already store, graph, retrieve, govern, compress, route, or monetize context. Open protocols and research are also advancing quickly.

These claims are therefore **not unique enough** for us:

- "Persistent memory for AI agents"
- "Context cloud"
- "Temporal knowledge graph"
- "Enterprise AI search"
- "Portable memory across AI apps"
- "One API for multiple memory providers"
- "Context receipts"
- "Token-efficient context for coding agents"
- "Route a question to the right data source"
- "Dynamic retrieval routing"
- "Context broker / context fabric"
- "Marketplace for MCP tools or context"

The strongest open gap found in this research is narrower and more defensible:

> **Operational competition between independent context providers.** For each request, choose a live provider from personal memory, enterprise search, temporal memory, warehouse semantics, code retrieval, CRM, web, or other context systems using explicit Context SLOs; fail over when the winner cannot satisfy them; safely audition alternates on shadow traffic; continuously maintain task-specific provider scorecards; and return one canonical evidence packet plus a route receipt.

Source routing already exists. Retrieval-pipeline routing already exists. Context fabrics already exist. The potentially distinctive product is the **OpenRouter-like operational layer for context providers**, where providers can be swapped and continuously compete on measured quality, currentness, latency, token efficiency, cost, permissions, and reliability.

This is still a market hypothesis, not a “we are definitely first” claim. Before any public first/only statement, repeat the market search and perform proper trademark/patent review where relevant.

---

## 2. Closest products and what to learn from them

| Product / category | What is strong | Weakness / opening for us |
|---|---|---|
| **Zep / Graphiti** | Temporal knowledge graph, provenance, invalidation of outdated facts, governed context, prompt-ready retrieval. | Primarily its own memory/context system. It can become a provider behind our router rather than requiring one memory backend to own the whole context plane. |
| **Mem0** | Drop-in agent memory, large developer mindshare, graph memory, enterprise/on-prem options, low-friction API. | Still a memory provider. Cross-provider failover, per-request SLO competition, independent quality measurement, and provider-neutral evidence remain separate problems. |
| **Supermemory** | Broad context infrastructure, connectors, memory/RAG primitives, hosted and self-hosted options. | Strong integrated stack, but an application still commits to that stack. Our layer should let it compete with other context systems per request instead of becoming another monolithic context backend. |
| **Cognee** | Open source, self-hostable, knowledge-graph-oriented memory and enterprise use cases. | Another memory engine rather than a neutral provider competition layer. Engines like this should be pluggable providers. |
| **Glean** | Proven enterprise demand; cross-tool search, permissions/connectors, employee productivity and onboarding use cases. | User feedback includes broad results and requests for finer filtering/source transparency. That becomes a router requirement: explicit source authority, freshness, reason-for-selection, and measurable context quality. |
| **Hyperspell** | Company context graph, 50+ connectors, permission-aware context served to many agents. | Builds a company brain. Our layer should route among a company brain, personal/local memory, warehouses, code retrieval, and other specialized context systems without one store owning all context. |
| **Snowflake Horizon Context** | Governed semantic/business context with enterprise security and consistency. | Tied to an enterprise data platform. It can become a high-authority provider for business semantics behind a neutral router. |
| **Corla / enterprise context brokers** | Scoped organizational context packages, MCP delivery, audit/governance. | Confirms that “context broker/control plane” alone is not a unique category claim. |
| **ContextRail (existing product)** | Makes organizational standards/durable truths available to AI tools through structured contexts and MCP workflows. | The name is unavailable to us, and durable organization-context delivery is already occupied. Our target is provider competition and SLO execution across independent systems. |
| **Impetus Context Fabric** | Enterprise semantic foundation connecting ontology, rules, policies, lineage and memory; explicitly markets MCP context routing and low-latency context delivery. | This proves that “dynamic context routing” and “context fabric” are not sufficient differentiation. Our moat must be independent-provider competition, live/fallback separation, shadow auditions, task-specific scorecards, and a neutral evidence contract. |
| **LangChain multi-source router pattern** | Routes questions to GitHub, Notion, Slack and other specialist sources, including parallel execution. | Source/agent routing is already a standard application pattern. We should sit one level lower as infrastructure and choose among context *providers/backends* using operational evidence, not merely classify a query by source. |
| **RetrievalRouter / retriever-routing research** | Shows query-aware routing can pick different retrieval modalities/architectures to improve the accuracy-latency frontier. | Validates adaptive retrieval, but focuses on retrieval pipelines. Our target adds provider health, enterprise policy, live failover, shadow evaluation, cross-provider evidence normalization, and ongoing production scorecards. |
| **memio / unified memory gateways** | Common interfaces over multiple memory systems and composable providers. | Adapter normalization is useful but insufficient. The missing value is continuously deciding which provider wins each task and proving why. |
| **Stanford Portable Memory / HCP and related portability work** | User-controlled, interoperable, consent/purpose-aware personal context. | Portability is not ours to claim as unique. We should interoperate with open formats rather than build lock-in. |
| **Entroly / coding context selectors** | Budgeted evidence selection, local-first context, receipts and reproducibility. | Shows receipts and context compression are adjacent. Our differentiated scope is operational routing across independent personal + enterprise + specialized context providers. |
| **Context Protocol** | Runtime discovery and a pay-per-response marketplace for MCP tools/data through one interface. | A context/tool marketplace is already occupied. We should not lead with marketplace economics; provider competition should be based on context quality/SLOs, with economics only as a later optional layer. |
| **MemRouter / SelRoute-style research** | Demonstrates that lightweight deterministic/embedding/query-type routing can avoid unnecessary LLM management overhead. | Reinforces our hot-path doctrine: no LLM by default; learned routing only after real benchmark and production scorecard data exists. |

---

## 3. User and organization feedback that should become requirements

Across enterprise reviews and memory-tool communities, recurring pain is more useful than vendor marketing:

1. **Wrong memory is worse than no memory.** Context needs supersession/effective-date semantics, not just accumulation.
2. **Users do not trust opaque selection.** We need raw, reproducible benchmark fixtures and a per-request reason-for-selection.
3. **Enterprise search can become broad or inconsistent.** Support source authority, fine-grained policy, freshness requirements, and visible omission reasons.
4. **Always calling an LLM for memory management wastes latency and money.** Deterministic or lightweight learned routing should handle the common path.
5. **Data ownership and lock-in matter.** Self-hosting, exportability, provider neutrality, tenant isolation, residency and purpose-limited access are core product requirements.
6. **Simple retrieval sometimes beats elaborate memory stacks.** Complexity must earn its cost in measured results.
7. **Reliability must include provider failure, not only answer quality.** A context backend can be slow, stale, permission-denied or unavailable; the application should not have to implement every fallback itself.

---

## 4. Our differentiated primitives

### 4.1 Context SLO

The caller describes the quality envelope instead of hard-coding a provider:

```json
{
  "task": "Prepare the context needed to answer this customer escalation",
  "token_budget": 4000,
  "max_latency_ms": 500,
  "freshness_max_age_seconds": 86400,
  "min_confidence": 0.8,
  "allowed_source_types": ["support", "policy", "crm"],
  "strategy": "balanced",
  "shadow": true
}
```

Future enterprise fields can include data region, sensitivity class, role, purpose, minimum source authority, maximum spend, and provider allow/deny lists.

### 4.2 Context Audition

The live winner answers the request. Alternate providers can receive an isolated shadow copy. Their results **never change the live response**, but can be scored afterward. This lets us learn which provider really performs best without gambling on users.

### 4.3 Context Scorecard

Provider reputation should be empirical and task-specific. Track separately:

- evidence recall / grounded task success
- stale or superseded evidence rate
- permission/policy failure rate
- p50/p95 provider and router latency
- token usage and useful-evidence density
- cost per successful context packet
- availability / timeout / error rate
- user correction or downstream outcome signals

A provider can be excellent for code and weak for HR policy; one global score would hide that.

### 4.4 Canonical Context Packet + Route Receipt

All providers normalize into one evidence contract. The response contains the minimal prompt-ready context and an audit receipt containing live/fallback/shadow attempts, selected evidence IDs, omissions, budget use, warnings, and a stable route fingerprint.

### 4.5 Temporal Truth Resolver

When providers disagree, source authority + effective time + provenance should determine what is current. The router should explain **why this fact is current** and **why the conflicting fact was omitted**, not silently average contradictions.

### 4.6 Context Lease (enterprise future)

A purpose-bound, short-lived permission envelope describing what this agent may retrieve for this task. This prevents “connected once = accessible forever” behavior and gives enterprises auditable least-privilege context access.

---

## 5. Why this can serve individuals, employees, and enterprises

### Individuals

One user-owned context path across saved content and future assistants, with transparent evidence and no requirement that one AI vendor own the person's memory. A local memory engine can remain the default zero-cost provider.

### Employees

The same work agent can use personal work memory, team knowledge, current company policy, project history, code context, CRM data and specialized systems while respecting role/purpose boundaries. The employee asks one question instead of knowing which system contains the answer.

### Enterprises

A company can preserve existing systems and vendors rather than rip them out. The router adds one policy and quality plane for agent traffic: select the best eligible backend, fail over when it is unhealthy/stale, continuously audition alternatives, and provide an audit artifact for every context packet. This directly reduces vendor lock-in and duplicated retrieval logic across internal agents.

---

## 6. Performance doctrine

We do **not** claim to be faster or more accurate than every competitor before measuring it. We build the product so such claims become falsifiable.

Initial engineering targets:

- deterministic routing in the common path; no LLM required
- one live provider call by default; extra calls only for fallback or explicit shadow evaluation
- router overhead measured separately from provider latency
- token budget must never be exceeded
- no cross-tenant evidence leakage
- strict freshness/confidence/source policies fail closed
- deterministic route fingerprint for the same routing decision
- provider errors isolated from caller and other providers
- reproducible benchmark fixtures before performance marketing
- p50/p95 latency, recall, stale rejection, useful-token density, cost and failover reported separately rather than collapsed into one vanity score

Future optimization should benchmark asynchronous timeouts, parallel fan-out, caches, circuit breakers, learned routing and lower-level/native hot paths only when profiling proves they materially help.

---

## 7. Build sequence

**CR-0 — Routing foundation (current PR)**

- provider-neutral request/evidence/packet/receipt schemas
- provider adapter protocol
- local AHME provider
- deterministic strategies: balanced, fastest, highest-trust, lowest-cost
- fallback on failure/empty policy-compliant evidence
- shadow evaluation that cannot alter live output
- confidence/freshness/source constraints
- dedup + token-budget packing
- route fingerprint and tests
- `/api/v1/context/route`

**CR-1 — Context SLO benchmark + provider scorecards**

- frozen benchmark fixtures with expected evidence
- p50/p95 router overhead and provider latency
- evidence recall, stale rejection and useful-token-density metrics
- provider capability/health registry
- rolling task/domain scorecards
- circuit breaker + hard provider timeout
- shadow audition reports that never affect live traffic
- baseline comparison against single-provider/static routing

**CR-2 — Temporal truth and conflict resolver**

- canonical claims with effective time and provenance
- contradiction/supersession detection
- source authority policies
- “why current” / “why omitted” explanations
- conflict benchmark suite

**CR-3 — Real multi-provider adapters**

- adapter SDK and capability discovery
- local memory first; then opt-in open/enterprise providers
- no paid dependency required for the default product
- encrypted credential boundary and data-residency policy
- adapter conformance tests

**CR-4 — Context competition engine**

- choose provider from real scorecards, not vendor claims
- per-task/provider quality profiles
- quality/latency/cost/trust Pareto routing
- safe optional fusion only when benchmarked better than single-provider output
- learned routing only after enough benchmark/shadow data exists

**CR-5 — Enterprise context gateway**

- RBAC/ABAC + purpose-bound Context Leases
- audit/export/retention controls
- SSO and organization policies
- deployment profiles: local, BYO cloud, managed
- region/residency-aware routing

**CR-6 — Ecosystem layer (only if traction proves it useful)**

- third-party provider directory and conformance badge
- public benchmark/scorecard format
- optional provider economics
- never let marketplace incentives override user policy or measured quality

---

## 8. Competitive rule going forward

Before copying a feature because a competitor has it, ask whether it improves one of our core advantages: **measured routing quality, currentness, trust, speed, token efficiency, portability, privacy, reliability, or auditability**. If not, do not add it.

The product should become difficult to remove because doing so would force every application/company to rebuild provider qualification, context SLO enforcement, failover, shadow evaluation, scorecards, conflict handling, evidence normalization and auditing — not because it has the longest feature list.
