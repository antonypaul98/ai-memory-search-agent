# N-06 Reverse Memory Closeout Candidate

Status: validation pending

## Canonical acceptance target

N-06 must answer the documented Reverse Memory question: **“What should I learn next for goal G?”**

## Implemented behavior under validation

- accepts an explicit tenant-scoped goal list through the authenticated Reverse Memory API;
- derives next-learning actions only from deterministic Gap Agent evidence;
- for a goal with zero saved coverage, recommends starting with a foundational source and records `memory_count: 0` as evidence;
- prioritizes reviewing stale existing knowledge before collecting additional material;
- recommends broader coverage and independent-source diversity only when the corresponding grounded gap exists;
- returns no suggestion for a goal that already satisfies the configured coverage, diversity, and freshness thresholds;
- performs no network fetch, autonomous memory write, or mandatory LLM call;
- preserves tenant isolation through the underlying Gap Agent and authenticated API boundary.

## Acceptance regression

`tests/test_reverse_memory.py::test_learning_next_for_explicit_goal_is_grounded_and_deterministic`

The regression calls `/api/v1/intelligence/reverse-memory` twice with an explicit `Distributed systems` goal and asserts:

1. both calls succeed;
2. both responses are identical;
3. exactly one goal is analyzed;
4. the recommendation is `start_foundation` with priority 1;
5. the action names the requested goal;
6. the evidence explicitly records zero current memories.

Existing Reverse Memory regressions additionally cover stale-review priority, well-covered suppression, tenant isolation, and authenticated-user API scoping.

## Validation gate

Do not mark N-06 complete until the full repository CI workflow passes on the PR containing this acceptance regression. If CI fails, fix the implementation or regression cause first and retain this document as validation-pending evidence.
