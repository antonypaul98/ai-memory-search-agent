# Model Router Research — 2026-08-27

**Status:** Active build track.  
**Goal:** Add an intelligence-routing layer beside the Context Router so the product can decide both **what context to use** and **which model should process it**.

## 1. The GitHub idea is real

There are several active open-source projects that aggregate free-tier capacity from multiple AI providers behind one OpenAI-compatible endpoint. The closest examples found during this review are:

- `freellmapi` / FreeLLMAPI variants — aggregate user-supplied keys across providers, track quotas, and fail over on rate limits.
- `freelm` — a free-tier client/gateway with provider failover, pacing, and live model discovery.
- LiteLLM — a mature multi-provider gateway/router with a common OpenAI-style interface, budgets, retries, fallbacks, and observability.
- OpenRouter itself now exposes `openrouter/free`, which selects among currently available free models and supports explicit `:free` model variants.

So **"combine free AI providers behind one endpoint" is not unique** and should not be marketed as our invention.

## 2. What we should build instead

Use the useful free-tier idea as one component of our larger architecture:

```text
AI / application request
        |
        +--> Context Router --> best evidence / knowledge path
        |
        +--> Model Router   --> best intelligence/model path
                              OR exact user-pinned model
```

The combined system is stronger than a free-token proxy because it can optimize two independent resources:

1. **Context:** relevance, freshness, trust, permissions, latency, token budget.
2. **Model:** task fit, quality, latency, available quota, free/paid preference, reliability.

A user can choose `auto` and let the router select, or choose `pinned` and require one exact model. A pinned request must never silently substitute another model.

## 3. Compliance boundary

The product must not depend on abusing free tiers. The safe architecture is **BYO credentials**:

- only use API keys/accounts the operator or organization owns and is permitted to use;
- never pool public/community keys;
- never create or rotate extra accounts to evade per-account limits;
- never resell or transfer upstream credentials;
- respect provider rate limits and usage terms;
- keep free-tier routing opt-in and suitable for experimentation/prototyping unless the upstream terms explicitly permit the intended production use;
- use paid/BYO enterprise capacity when reliability, resale, or production terms require it.

FreeLLMAPI's own May 2026 ToS review reaches a similar practical conclusion: provider terms differ, some free tiers are explicitly experimental/evaluation-only, and single-user self-hosted use is materially different from operating a public resale proxy. Provider terms change, so our catalog must treat policy metadata as versioned data rather than a permanent assumption.

## 4. Why we should not hard-code "billions of free tokens"

The available free capacity changes constantly. Some providers limit requests, some tokens, some per-model quotas, and many do not expose a standard remaining-quota API. Marketing a fixed number would become stale quickly.

Instead the router should expose **Available Capacity**:

- configured providers/models;
- local requests/tokens used today;
- optional operator-entered daily token/request budgets;
- provider health/cooldowns from real responses;
- upstream 429/5xx failover;
- later: provider-specific live quota/discovery adapters where an official endpoint exists.

This makes the system accurate even when free tiers change.

## 5. MR-0 implementation in this PR

- provider-neutral `ModelRouteRequest` / `ModelRouteResponse` contracts;
- `auto` and strict `pinned` modes;
- deterministic task classification for general, fast, reasoning, coding, summarization, and extraction requests;
- BYO provider catalog using environment-variable references for secrets;
- built-in OpenRouter `openrouter/free` route when the operator supplies an `OPENROUTER_API_KEY`;
- generic OpenAI-compatible provider adapter plus Ollama/local support;
- free-tier preference in automatic routing;
- task/quality/latency-aware ordering;
- durable tenant-scoped request/token accounting in SQLite;
- optional local daily request/token budgets;
- automatic failover on provider failures;
- temporary cooldown after 429/5xx failures;
- no silent fallback when the user pins a model;
- model catalog API showing configured status and locally estimated remaining budget without exposing keys;
- deterministic route fingerprint that hashes the prompt rather than storing it in the fingerprint.

API surface:

```text
POST /api/v1/models/route
GET  /api/v1/models/catalog
```

## 6. Next build: MR-1

MR-1 should make the model side as measurable as the Context SLO work:

- provider/model health scorecards;
- p50/p95 latency and failure rate;
- task-specific quality benchmarks;
- live free-model discovery where provider APIs support it;
- versioned quota/terms metadata;
- streaming support;
- tools / structured-output capability enforcement;
- sticky conversation routing so a conversation does not switch models unnecessarily;
- paid-cost ceilings and cost-per-success metrics;
- optional shadow auditions of alternate models.

After both routers have benchmark data, add a unified **Context + Intelligence route** where one request can specify both Context SLOs and Model SLOs.

## 7. Product rule

Free capacity is a useful acquisition and experimentation feature, not the moat. The moat should become the independent routing data: which context source and which model actually perform best for each class of task under real latency, trust, quota, cost, and policy constraints.
