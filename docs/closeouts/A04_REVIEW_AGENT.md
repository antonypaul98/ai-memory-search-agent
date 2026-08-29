# A-04 Review Agent Closeout

Status: **Validated complete for the AGENT_BIBLE A-04 acceptance contract.**

## Acceptance contract

`AGENT_BIBLE.md` defines A-04 as the spaced-review agent and requires it to surface memories for active goals that have not been viewed in 14+ days.

## Implementation evidence

- `app/services/review_agent.py` builds a deterministic, tenant-scoped review queue from registry/reflection metadata.
- Memories with durable review schedules use `next_review_at` as the authoritative due boundary.
- Memories without review history use the configured stale-view threshold.
- Goal filtering is deterministic and scoped to the authenticated `user_id`.
- Never-viewed goal memories are eligible and prioritized without inventing review history.
- Output includes source URL/title plus the original goal/reflection context needed for a grounded review prompt.

## Regression evidence

`tests/test_review_agent.py` directly verifies:

- a memory last viewed 20 days ago is surfaced with `stale_days=14` while a 2-day-old memory is excluded;
- never-viewed memories are prioritized;
- goal filtering is deterministic;
- cross-tenant memories are excluded;
- the API derives the tenant from authentication rather than request-controlled identity.

`tests/test_review_schedule.py` separately validates durable scheduling and review-result behavior.

## Safety and privacy boundary

- Review selection is deterministic; no LLM is required.
- Reads are tenant-scoped.
- The agent does not alter content or create new memories while building a queue.
- Review-result writes remain constrained to review metadata through the existing scheduling service.
- No Jarvis-specific capability is part of this closeout.

## Result

A-04 is complete for its documented acceptance criterion. Future UX or notification improvements must not be treated as blockers unless promoted into the canonical Memory Search acceptance contract.
