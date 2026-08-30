# N-01 Consensus Engine closeout

Status: validated implementation; pending this PR's full CI gate.

## Acceptance mapping

The canonical N-01 acceptance criteria in `KNOWLEDGE_ENGINE.md` are satisfied by the existing implementation plus the acceptance regression in this change:

1. **Comparison queries surface both sides with citations/evidence.** `ChatService` runs `ConsensusEngine` for comparison and cross-video queries. When a conflict is detected, `conflict_preserving_answer()` renders both source titles and both claim texts rather than synthesizing them into one false statement. The response retains the normal retrieved source list.
2. **Consensus weight is visible in the UI.** The Ask workspace renders `consensus.consensus_weight` as a percentage together with consensus status and independent source count.
3. **Contradictory claims are not merged into one sentence.** Numeric and negation mismatches are represented as explicit conflict sides. For a conflicting comparison, the consensus conflict rendering replaces a potentially over-confident synthesized answer.

## Safety and architecture

- deterministic analysis over evidence already retrieved for the authenticated tenant;
- no external research or network fetch inside the consensus engine;
- no memory writes or autonomous mutation;
- source independence is keyed by canonical retrieved source ID, so multiple chunks from one source do not create false consensus;
- agreement weights and conflicts retain source IDs/titles and claim text;
- no mandatory LLM call is introduced by consensus analysis.

## Regression evidence

- `tests/test_consensus_engine.py` covers independent-source requirements, agreement weight, numeric conflict, negation conflict, unrelated-source inconclusive behavior, and same-source duplicate protection.
- `tests/test_consensus_acceptance.py` locks conflict preservation plus the Ask UI's visible weight/source/conflict contract.
- `app/services/chat_service.py` integrates consensus only for comparison/cross-video queries and preserves the normal evidence response.

N-01 should be marked complete only after this branch passes the repository-wide CI gate.
