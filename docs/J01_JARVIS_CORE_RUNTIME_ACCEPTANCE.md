# J01 Jarvis Core Runtime Acceptance

J01 establishes the smallest useful Jarvis orchestration boundary on top of the
completed Memory Search system.

## Contract

Jarvis accepts one authenticated natural-language request, asks the existing
`CommandRouterService` for a deterministic plan, and automatically executes only
intents already classified as safe/read-only. Search and grounded-memory questions
therefore reuse the existing tenant-scoped Search/Chat services and evidence model.

J01 intentionally does **not** introduce an LLM autonomous planner, a second tool
registry, or a new memory store. It does not grant new write authority.

## Safety boundary

Natural-language save, bulk import, destructive, external, or unknown work cannot
be converted into an action merely by reaching the Jarvis endpoint. Non-read-only
intents return `action_gated`; later gates must integrate explicit permissions and
approval without weakening the accepted Memory Search confirmation boundaries.

## Exit evidence

J01 is accepted only when:
1. core/API regressions pass;
2. repository required CI passes on the exact PR head;
3. the PR is mergeable and merged safely;
4. canonical main contains the implementation and ledger state.
