# Context Router Research — 2026-08-27

**Status:** Active product direction and competitive guardrail.  
**Engineering label:** Context Router. **Do not use “ContextRail” as the product name** — an active AI standards/context platform already uses it. Final branding requires a separate name/trademark/domain scan.  
**Principle:** Do not become another generic vector database, memory API, enterprise search product, or prompt compressor. Build the neutral execution layer that decides **which context system to trust for this request, under this user's policy, latency, freshness, token, and cost constraints**.

---

## 1. Market conclusion

The AI memory/context market is real and increasingly crowded. Several strong products already store, graph, retrieve, govern, or compress context. There are also open standards and small projects for portable memory and unified memory-provider interfaces.

That means these claims are **not unique enough** for us:

- "Persistent memory for AI agents"
- "Context cloud"
- "Temporal knowledge graph"
- "Enterprise AI search"
- "Portable memory across AI apps"
- "One API for multiple memory providers"
- "Context receipts"
- "Token-efficient context for coding agents"

The open gap worth pursuing is the combination of **dynamic provider routing + policy enforcement + failover + shadow evaluation + canonical evidence normalization + token-budget packing + temporal/conflict handling + an auditable route receipt**, usable by personal assistants, employee agents, and enterprise systems.

We should treat uniqueness as a continuously tested market hypothesis, not a marketing fact. New competitors must be re-checked before public "first" claims.

---

## 2. Closest products and what to learn from them

| Product / category | What is strong | Weakness / opening for us |
|---|---|---|
| **Zep / Graphiti** | Temporal knowledge graph, provenance, invalidation of outdated facts, governed Context Lake, prompt-ready context; Zep advertises sub-200ms retrieval. | Primarily its own memory/context system. Our opportunity is to route across Zep-like systems plus enterprise/personal/local sources rather than require one memory backend. |
| **Mem0** | Drop-in agent memory, large developer mindshare, graph memory, enterprise/on-prem options, low-friction API. | Still a memory provider. Provider choice, cross-provider failover, per-request SLA routing, and independent evidence normalization remain separate problems. |
| **Supermemory** | Broad context infrastructure, connectors, hosted and self-hosted options, simple developer integration. | A proxy/automatic memory layer can add latency and reduce caller control over exactly what was injected. We should make every selection explainable and policy-bound. |
| **Cognee** | Open source, self-hostable, knowledge-graph-oriented memory, inexpensive usage pricing, production case studies. | Another memory engine rather than a neutral routing/competition layer. We can use engines like this as providers instead of trying to replace every engine. |
| **Glean** | Proven enterprise demand; excellent cross-tool search, permissions/connectors, employee productivity and onboarding use cases. | User reviews mention broad results, limited filtering/source transparency, conflicting or superseded sources, and occasional slowness/inconsistency. Those become explicit router requirements: source policy, temporal conflict handling, deterministic selection, latency budgets. |
| **Hyperspell** | Company context graph, 50+ connectors, agent-neutral access. | Builds a company brain. Our layer should also route between company brain, personal memory, local sources, and specialized context systems without one store owning all context. |
| **Corla / enterprise context brokers** | Scoped organizational context packages, MCP delivery, audit/governance. | Confirms that "context broker/control plane" alone is not a unique category claim. We need routing competition, measurable SLAs, shadow benchmarks, and cross-provider fallback as first-class primitives. |
| **ContextRail (existing product)** | Makes organizational standards/durable truths available to coding AI tools through MCP and verification workflows. | Its existence makes the name unavailable to us and confirms that durable organization-context delivery is already occupied. Our scope is dynamic provider selection and context execution across many context systems, not a standards library. |
| **Snowflake Horizon Context** | Governed enterprise semantic/business context; strong fit for data estates and consistent business logic. | Tied to an enterprise data platform. It can become a provider behind our router rather than define the whole user's context universe. |
| **memio / unified memory gateways** | One interface across Mem0, Zep, Chroma, Letta, Qdrant, Supermemory; composable providers. | A common adapter is useful but not enough. We need the router to decide dynamically which backend(s) win for each request and prove the decision. |
| **Stanford Portable Memory / HCP and other portability efforts** | User-controlled, interoperable, consent/purpose-aware personal context is an important emerging direction. | Portability is not ours to claim as unique. We should support open portable formats/protocols instead of inventing a proprietary prison. |
| **Entroly / coding context routers** | Budgeted evidence selection, local-first operation, recoverable context, detailed receipts and reproducible claims. | Strong proof that receipts and context compression are already adjacent. Our differentiated scope is provider-neutral context routing across personal + enterprise + specialized context systems, not only selecting/compressing one corpus. |
| **MemRouter research** | Shows a lightweight learned/embedding router can beat an LLM memory manager while reducing write-side p50 latency dramatically in its controlled benchmark. | Reinforces our hot-path rule: deterministic/embedding routing first; use an LLM only for ambiguous decisions that justify the latency/cost. |

---

## 3. User and organization feedback that should become requirements

Across enterprise reviews and memory-tool community discussions, recurring pain is more useful than competitor marketing:

1. **Wrong memory is worse than no memory.** Systems often accumulate facts without a deterministic model for supersession, versioning, or effective dates.
2. **Users do not trust opaque selection.** Developers repeatedly ask for raw, reproducible side-by-side benchmarks rather than cherry-picked vendor scores.
3. **Enterprise search can become broad or inconsistent.** Users want tighter source controls, better filtering, freshness awareness, and visibility into why a source was chosen.
4. **Always calling an LLM for memory management is unnecessary overhead.** Fast deterministic or lightweight learned routing should handle the common case.
5. **Data ownership and lock-in matter.** Self-hosting, exportability, provider neutrality, tenant isolation, and purpose-limited access are product requirements, not enterprise polish to add later.
6. **Simple systems can beat elaborate memory stacks on some workloads.** Complexity must earn its latency and accuracy cost in benchmarks.

---

## 4. Our differentiated primitive: the Context Route

A caller should be able to request:

```json
{
  "task": "Prepare the context needed to answer this customer escalation",
  "token_budget": 4000,
  "max_latency_ms": 500,
  "freshness_max_age_seconds": 86400,
  "min_confidence": 0.8,
  "strategy": "balanced",
  "shadow": true
}
```

The router, not the application, should decide the live context path.

Candidate providers can eventually include:

- the user's local/personal memory
- company search / knowledge systems
- temporal graph memory
- CRM / support / ticket context
- code/repository context
- governed warehouse/semantic context
- fresh public information when policy explicitly permits it
- third-party memory providers

The live path stays minimal. If it fails or violates request constraints, the router falls back. In shadow mode, alternate providers are evaluated without changing the live output.

Every provider's result is normalized to canonical evidence and packed into the explicit token budget. The response includes a **Context Receipt** with provider attempts, selected evidence IDs, omissions and reasons, policy/freshness decisions, token estimate, warnings, and a deterministic route fingerprint.

---

## 5. Why this can serve individuals, employees, and enterprises

### Individuals

One user-owned context path across saved content and future assistants, with transparent evidence and no requirement that one AI vendor own the person's memory.

### Employees

The same agent can retrieve personal work memory, team knowledge, current company policy, project history, and role-specific context while keeping personal/work scopes distinct. This directly attacks context switching and repeated "where was that?" searching.

### Enterprises

A company can keep existing systems of record and context products while adding one policy/routing layer for agent traffic. The router can enforce tenant/role/purpose/data-residency rules, choose the fastest trusted provider, fail over when a backend is unhealthy, and produce an audit artifact for every packet.

---

## 6. Performance doctrine

We do **not** claim to be faster or more accurate than every competitor before measuring it. We build the product so those claims can become falsifiable.

Initial engineering targets:

- deterministic routing in the common path; no LLM required
- one live provider call by default; additional calls only for fallback or explicit shadow evaluation
- token budget must never be exceeded
- no cross-tenant evidence leakage
- strict freshness/confidence/source policies fail closed
- deterministic route fingerprint for the same routing decision
- provider errors isolated from the caller and from other providers
- public/reproducible benchmark fixtures before performance marketing
- measure p50/p95 route overhead separately from provider latency
- measure evidence recall, stale-fact rejection, token use, cost, and failover behavior separately rather than collapse them into one vanity score

Future optimization work should benchmark parallel fan-out, learned routing, caching, provider health scores, and Rust/native hot paths only when profiling proves they are necessary.

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

**CR-1 — Benchmark + provider health**

- frozen routing benchmark fixtures
- p50/p95 router overhead and provider latency
- evidence recall / stale rejection / token efficiency metrics
- rolling provider health and circuit breaker
- shadow-result scorecards

**CR-2 — Temporal truth and conflict resolver**

- canonical facts/claims with effective time and provenance
- contradiction/supersession detection
- source authority policies
- "why current" / "why omitted" explanations

**CR-3 — Real multi-provider adapters**

- adapter SDK and capability discovery
- local memory first; then opt-in enterprise/open providers
- no paid dependency required for the default product
- encrypted credential boundary and data-residency policy

**CR-4 — Context competition engine**

- learned routing only after benchmark data exists
- per-task/provider quality profiles
- cost/latency/trust Pareto routing
- automatic fallback and optional safe fusion

**CR-5 — Enterprise context gateway**

- RBAC/ABAC + purpose-bound context leases
- audit/export/retention controls
- SSO and organization policies
- deployment profiles: local, BYO cloud, managed

---

## 8. Competitive rule going forward

Before copying a feature because a competitor has it, ask whether it improves one of our core advantages: **trust, routing quality, speed, token efficiency, portability, privacy, or auditability**. If not, do not add it.

The product should win because removing it would force an application or company to rebuild provider selection, context policy, failover, benchmarking, and evidence accountability — not because it has the longest feature list.
