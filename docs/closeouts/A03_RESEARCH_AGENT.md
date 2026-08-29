# A-03 Research Agent Closeout

**Status:** Validated

**Scope:** Memory Search Agent only. Jarvis-specific voice, vision, gesture, spatial, hologram, and ambient-hardware work remains out of scope.

## Acceptance criterion

`AGENT_BIBLE.md` requires the Research Agent to answer a **3-hop** memory research question with **at least three distinct cited sources**.

Executable evidence now locks that requirement directly:

- `tests/test_research_agent.py::TestResearchAgent::test_three_hop_acceptance_returns_three_distinct_cited_sources`
  - runs the agent with `depth=3`;
  - verifies exactly three bounded retrieval hops;
  - verifies three distinct saved-memory source identifiers;
  - verifies hop provenance is retained as `1, 2, 3`;
  - verifies each source marker and citation reference appears in the report;
  - verifies every retrieval remains scoped to the authenticated `user_id`.

Existing regression coverage also verifies:

- requested depth is bounded to the specified 1–3 range;
- the source budget cannot be configured below the acceptance minimum;
- empty memory fails closed without fabricating sources;
- the API path uses the authenticated tenant identity;
- invalid depth is rejected at the API boundary.

## Implementation evidence

`app/services/research_agent.py` already provides the smallest deterministic implementation required by A-03:

- bounded multi-hop retrieval over the user's saved memory;
- `SearchService` calls explicitly scoped by `user_id`;
- deterministic source deduplication using source type plus stable source identifier;
- source markers mapped directly to retrieved citation references;
- an explicit no-evidence response when saved memory has no support;
- no external research fetches and no memory writes.

The implementation therefore preserves canonical/provenance boundaries and does not require an LLM to perform the research loop. Optional model-assisted synthesis remains an on-demand concern handled by the existing grounded synthesis/provider boundary rather than becoming an autonomous planner dependency.

## Safety and privacy boundary

- Default behavior is read-only.
- No autonomous external network access is introduced.
- No autonomous memory writes or report persistence are introduced.
- Cross-tenant retrieval is not permitted; the authenticated `user_id` is propagated on every hop.
- Returned citations are derived only from retrieved memory evidence.
- Empty or insufficient evidence is surfaced rather than invented.

## Scope boundary

This closes the currently stated A-03 acceptance criterion. Optional report-saving remains subject to an explicit approval-gated write path if added later. Knowledge-graph traversal is future-compatible but is not required by the current A-03 acceptance contract and is not fabricated here merely to satisfy stale architecture wording.
