# Current Memory Search Build State

Updated: 2026-09-15

This file records the implementation state used during the active Memory Search completion pass. `MASTER_SPEC.md` remains the canonical feature inventory; this document exists to prevent implementation/documentation drift while that larger inventory is reconciled.

## EventBus privacy follow-up — 2026-09-15

The next implementation extends production privacy to tenant activity and webhook
subscription metadata. Export includes every event (no interactive-page cap),
reapplies the existing payload credential-redaction policy, and excludes delivery
URLs entirely. Event/subscription deletion shares one transaction; a failed event
delete rolls back subscription removal. Two-tenant Postgres regression covers
105 events per tenant, rollback/retry, blank-owner rejection and the combined
live-worker privacy lifecycle. Exact-head CI is required before merging.

This does not cancel already dispatched webhooks or fence concurrent producers.
P-03 stays Partial. Next: complete canonical export enumeration/history and
residual graph/intelligence erasure, then durable account/write-fencing semantics.
The table inventory below remains the boundary checklist; gate stays 22/29.

## Current continuation — 2026-09-15

Verified main `4f4ed118749447af730b19b1cd211e6366b3f5f5` includes #295
(model-usage privacy primitives); exact-head CI #1125 and main CI #1126 passed.
#286/#287, #289/#290/#291/#292 and #294 are merged. Their pending references
below are historical. #294's combined live-worker privacy acceptance passed
CI #1123; it establishes its exercised memory/feedback boundary, not full-account erasure.

#296 merged as `8e1cc8ab59ab59c6f2bff153829f75c04c26ab3f`. Exact-head
CI #1127 / run 34912421871 passed 1,191 Python tests, 27 extension tests and
benchmark. Model usage is integrated into PrivacyService export and production
erasure; real Postgres failure/retry and neighboring-tenant preservation passed.

The [operational privacy inventory](P03_OPERATIONAL_PRIVACY_INVENTORY.md)
accounts for all 52 literal PostgreSQL table declarations. It records incomplete
export pagination, residual graph/intelligence/capture/import/job/agent records,
and missing account/session/write-fencing integration. This is a source audit,
not full-erasure acceptance. EventBus was the next bounded implementation identified by this audit; see the
follow-up above for its acceptance boundary.
P-03 remains **Partial**. Next: operational privacy inventory, especially EventBus,
agent state, captures/imports, jobs and auth/session lifecycle. The erasure helper
currently covers memory, feedback and model usage; it does not revoke accounts or
prevent concurrent writers from recreating data. The public delete-memories API
remains a memory-only operation. No live deployment migration occurred.

Jarvis Gate: 22/29 cleared — 7 remaining (continuity baseline; unchanged).

## Verified continuation — 2026-09-14 (review of #283)

GitHub main was verified at `c3ffdd8456036e8cfb5eb9f817e5bb7b2994dc4d`
(#282); main CI run 34872101043 passed. #273–#282 are merged; do not rebuild
their accepted slices. #283 original head `0d188a63842466a3f723fcd240961276ae2a66a6`
passed CI #1097 / run 34872219540 with 1,167 Python tests, extension tests and
benchmark, but its broad closure claim did not survive code review.

P-03 stays **Partial for implementation**, not merely pending operator deployment.
Real HierarchicalStore deletion still swallowed backend failures and unscoped
cleanup could remove owned vectors. Generic connector hierarchy calls still
omitted the tenant. #284/#285 repair these separate defects and require exact-head
CI before merge. Their acceptance executes actual Chroma/selected Postgres stores,
rather than inferring runtime safety from helper mocks or source-text assertions.

Next after these repairs: canonical embedding references must match tenant-scoped
stored vector IDs; legacy inventory failures must fail closed; complete the
operational privacy inventory and integrated production acceptance. See
[P03 evidence](P03_FINAL_ACCEPTANCE_EVIDENCE.md). No live data migration occurred.
Environment-owned credentials, exact deployment ownership, preview review and any
necessary maintenance approval remain operator prerequisites, separate from CI.

### Validated follow-up

#285 passed exact-head CI #1099 / run 34873132249: 1,168 Python tests,
extension checks and benchmark. Merged as
`c971a07902c8e0ea3a093bd86dea28e20f9b4d70`. Generic connector hierarchy
ownership, actual PDF finalization/retrieval and retry are accepted within that
test boundary. #284 then passed exact-head CI #1098 / run 34872976874 with 1,172 Python tests,
extension checks and benchmark, merging as
`3cd303ec922bf066d1fa6efaee2fb0d9c3020296`. Actual vector-delete failures now
preserve canonical ownership for retry and legacy cleanup preserves known owners.
The preceding pending #284/#285 statements are historical review findings.
Next: repair canonical embedding references to resolve to the tenant's actual
stored vectors; then fail-closed legacy inventory and remaining privacy acceptance.

### Gate accounting

**Jarvis Gate: 22/29 cleared — 7 remaining (historical continuity baseline).**
The latest handoff explicitly requests preserving that baseline while reconciling
accounting. It is not a fresh verified tally. Earlier 2/29 entries below counted a
narrower continuation and are historical; no merged work is lost or reset.
[Gate evidence ledger](JARVIS_GATE_LEDGER.md) contains exactly 29 explicitly new
candidate acceptance groups with criteria, status, source revisions, tests and
remaining work. It does not invent a mapping to the missing historical inventory.
Do not replace the historical count by summing candidate rows until the all-version
reconciliation is complete. U-03 briefing still lacks a dedicated implementation;
optional P-07, deferred C-09 and Jarvis-specific U-05 are distinguished explicitly.

Strict Memory Search-first sequencing applies. Preserve the Home/Career work
already merged elsewhere (including #268), but do not advance it before all
Memory acceptance and stability requirements pass. Open older Career/social
branches do not displace P-03. Historical parallel-work authorization below is
superseded by the current instruction.

## Verified continuation — 2026-09-13

Starting main: `3c136cbc61bfb79c0f73e6fdb7878f2cb5f504c7`. Reviewed recent merged
PRs #238–#247 and open #248; #248 passed CI and was merged as
`c172d26919cc86f8b4db8bb18551b9dd5687fcb0`.

**Gate reconciliation: recorded 2/29; actual full 29-item count is not verifiable.**
The handoff's approximately 22/29 is unsupported by a repository inventory. The
historical section below explicitly states that no full 29-checkpoint inventory
exists. Do not create a fictional checkpoint 23, reset completed work, or count
individual regression PRs as new gate checkpoints. P-03 remains Partial.

PR #249 repaired a real privacy defect: tenant-owned Postgres lexical rows now
get deleted even when another tenant saved the same external source. A lexical
delete failure propagates before canonical ownership is removed, enabling retry.
Its selected PrivacyService integration executes relational construction, search,
export and deletion with SQLite connections rejected, including shared-source
isolation and injected failure/retry. Chroma dependencies are explicitly isolated;
this does not certify the full ingest/worker/vector profile.

#249 also rejects future-dated Home Agent consent. CI run
[34785396499](https://github.com/antonypaul98/ai-memory-search-agent/actions/runs/34785396499)
passed 1,027 Python tests plus extension tests and benchmark; merged as
`2b83a29df3fb031eca5fda3505f2c46b8bdff7f0`.

Local broad validation: 1,014 passed, 11 skipped, two failures. Both failures
reproduce against unchanged main in this environment: public-host DNS resolution
and embedding-model loading. Real Postgres/Redis acceptance is supplied by CI.
No live production migration was run.

Home Agent already had Postgres sightings, authenticated last-seen/history,
consent, structured detections and bounded capture sessions. The current image
extension adds local image decoding, a local OWL-ViT adapter, private image evidence,
canonical class records, transactional multi-object observations, tenant-scoped
evidence deletion and a CLI. See `HOME_AGENT_V1.md` for the precise acceptance
boundary. V1 remains incomplete until trained-detector/demo and all acceptance
items are validated. Current user authorization permits this modular Home Agent
foundation alongside unfinished Memory Agent work; this supersedes the historical
blanket exclusion of vision below, without declaring the Jarvis transition complete.

Home image continuation is tracked in PR #250. Local trained OWL-ViT inference
on the pinned public sample detected two cats and a remote control in 486 ms
after loading; this is not household/keys accuracy certification. A separate
`Home vision smoke` workflow executes trained detection with real Postgres and
last-seen retrieval; its current-head outcome must be verified before merge.
The image ingest gate is rechecked after inference so expired consent cannot
retain private evidence. Acceptance documentation is in `HOME_AGENT_V1.md`.

Next Memory execution: complete the updated relational runtime audit and remaining
agent/event/OAuth/feedback paths, full ingest/worker failure/isolation execution,
and deployment-specific migrated lexical parity. Next Home execution: validate
trained detection with real household images, complete conflict-aware responses,
alias/instance/location metadata and authenticated image/evidence interfaces.

## Active continuation: P-03 artifact migration

This dated section supersedes the historical next-work ordering below for the current session. P-03 production-wide Postgres migration remains **Partial** and is the active priority. The root inventory and historical reconciliation lists still require conservative audit; they are not a basis for declaring all versions complete.

**Jarvis Gate: 2/29 cleared — 27 remaining**

This carries forward the explicitly established 1/29 session baseline from PR #163, rather than inventing an older project-wide tally. The repository does not yet define the full 29-checkpoint inventory; this running count must not replace the complete Memory Search acceptance/stability gate.

| Counted checkpoint | Evidence and boundary |
| --- | --- |
| 1. Preview-first legacy ingest-artifact migration | PR #163 established the migration. PR #166 repairs its missing-ownership-proof gap and ensures a consistent SQLite snapshot. These repairs are not counted as extra checkpoints. |
| 2. Real-Postgres ingest-artifact migration acceptance | PR #166 / commit `99519a12af0af8d935c5336ca045ea5789754912` / [CI run 34494127491](https://github.com/antonypaul98/ai-memory-search-agent/actions/runs/34494127491): 791 Python tests, no skips; real-Postgres retry, rollback, target preservation and tenant isolation; 27 extension tests and benchmark passed. |

The next P-03 work is the remaining relational SQLite-write audit, representative lexical parity on migrated state, broader production-profile failure/isolation integration, and zero-SQLite-write proof for the supported multi-worker profile. PRs #243/#245/#246 now gate legacy schema migration for the selected Postgres profile; production-wide SQLite retirement is still not claimed. See `P03_POSTGRES_MIGRATION.md` for exact boundaries and operator instructions.

No live production database migration was executed. All planned Memory Search versions and acceptance criteria must be complete before Jarvis-specific work. After that explicit completion gate, the first major Jarvis module is the Career/Job Agent.

## Validated platform foundation

The production/runtime foundation is now validated for the currently documented scope:

- readiness/liveness and the current observability baseline;
- durable tenant-scoped Event Bus, audit events, request correlation, privacy-safe webhook delivery, and recursive credential redaction;
- SQLite compatibility for local/single-node operation;
- Postgres durable job state with atomic claims/leases and tenant-safe controls;
- Redis consumer-group wake transport carrying opaque job wake markers only;
- fail-closed protection against split-worker SQLite deployments.

## Validated Memory Search closeouts

Recent acceptance closeouts include:

- F-12 grounded answer synthesis;
- F-16 optional, on-demand LLM providers with deterministic fallback;
- F-23 opt-in bookmark re-import;
- F-29 Connector SDK contract;
- F-30 SQLite registry client;
- F-33 Knowledge Graph & Entity Intelligence with deterministic temporal facts, tenant-safe entity merge/dedup, a visible Entity Merge Review UI, and literal `confirm: true` required at the generic merge API boundary;
- N-02 claim/evidence verification;
- A-01 deterministic agent runtime with tenant isolation and approval gates;
- A-02 approved deterministic ingest-agent rules with canonical deduplication;
- A-03 bounded three-hop research with at least three distinct cited saved-memory sources;
- A-04 spaced Review Agent queue for active-goal memories stale for 14+ days;
- A-05 deterministic Capture Triage with canonical queue deduplication, tenant-scoped existing-memory checks, explicit junk/unsafe URL rejection, and full CI validation;
- A-06 deterministic Gap Agent analysis with evidence-backed actions, tenant isolation, explicit zero-memory goal handling, a per-goal actionable notification contract, and full CI validation;
- A-07 deterministic Consolidation Agent analysis remains read-only and tenant-scoped, and its entity-merge write boundary requires authenticated explicit `confirm: true` before reusing the existing tenant-safe merge service;
- N-01 deterministic Consensus Engine preserves explicit cross-source conflicts, computes source-backed agreement weight, avoids false source independence, and exposes consensus status/weight/source count plus both conflict sides in the Ask workspace;
- N-04 Gap Engine grounds missing-knowledge findings in observable coverage, source diversity, and review state rather than inventing unsupported curriculum topics;
- N-06 Reverse Memory deterministically turns grounded goal gaps into next-learning actions without mandatory AI;
- N-07 Learning Evolution uses bounded tenant-local feedback to evolve ranking without re-ingest or mutation of evidence scores.

N-04, N-06, and N-07 were carried together by the validated stacked PR #93 after CI run #656 passed and were squash-merged into `main` as commit `277063394e95da6b47d25a7d0d7d68064598b848`.

F-33 passed full CI in PR #94 / run #658 and was squash-merged into `main` as commit `4c466d73d136b003462a81b91d1738af6f700e17`.

The implementation also already contains trust, connectors, exports, and agent activity surfaces. Their canonical acceptance status must continue to be audited against executable tests before broad milestone closure.

## Current validation gate: source-of-truth reconciliation after F-33

F-33 is no longer validation-pending. The current gate is the required reconciliation of root source-of-truth documents against validated executable behavior.

Reconcile `MASTER_SPEC.md`, `FEATURE_IDEAS.md`, `CONNECTOR_SDK.md`, `KNOWLEDGE_ENGINE.md`, `AGENT_BIBLE.md`, and `README.md` conservatively. Correct only rows whose exact acceptance behavior is backed by implementation and automated tests. Do not infer completion merely from a service, route, or file existing.

The first reconciliation targets are the rows now known to be stale from completed closeouts: F-12, F-16, F-23, F-29, F-30, F-33, N-01, N-02, N-04, N-06, N-07, and A-01–A-07. Changes must preserve the distinction between a fully accepted feature and optional/future enhancements that remain outside that feature's current acceptance contract.

## Next required Memory Search work

1. Finish the root-document reconciliation for already validated closeouts, starting with knowledge-engine and feature-inventory rows.
2. Audit the remaining graph / connector / platform / trust / export rows individually against their exact documented acceptance criteria, tenant/privacy/provenance requirements, and executable tests.
3. Where an acceptance criterion is genuinely missing, implement the smallest correct behavior plus regression coverage before changing its status.
4. Run the final Memory Search acceptance/stability gate only after every planned item is reconciled.

Known documentation drift to resolve during that reconciliation:

- `FEATURE_IDEAS.md` still marks already validated F-12, F-16, F-23, F-30, N-01, N-02, N-04, N-06, N-07, and A-01–A-07 work as Partial/Planned/Missing;
- `FEATURE_IDEAS.md` uses the old A-06/A-07 Policy/Guardrails and Agent Audit UI labels, while `AGENT_BIBLE.md` and the validated implementation define the active A-06/A-07 closeouts as Gap and Consolidation Agents;
- `MASTER_SPEC.md` and `KNOWLEDGE_ENGINE.md` still describe consensus/agents/scale-out capabilities as planned even where executable implementation now exists;
- `KNOWLEDGE_ENGINE.md` still describes F-33 temporal facts and entity merge/dedup UI as missing even though PR #94 validated and merged both acceptance paths;
- several connector, Postgres/Redis, export, trust, cross-source-dedup, and other knowledge-intelligence rows appear stale and must be audited individually rather than mass-marked complete.

Graph / connector / platform / trust / export rows must each be evaluated against their exact documented acceptance criteria and tenant/privacy/provenance requirements. Run the final Memory Search acceptance/stability gate only after every planned item is reconciled.

No Jarvis transition is permitted merely because the agent catalog or knowledge-engine implementations exist.

## Jarvis transition gate

Jarvis-specific voice, vision, gesture, spatial, hologram, ambient-capture, or physical-interface work remains out of scope. Transition is permitted only after every planned Memory Search version and acceptance criterion is complete, stable, and validated with no known reproducible defect in covered behavior.
