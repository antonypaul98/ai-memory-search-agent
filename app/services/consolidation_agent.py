"""Phase 4 Consolidation Agent: deterministic maintenance suggestions only."""

from __future__ import annotations

import re
from collections import defaultdict

from app.config import Settings
from app.db.knowledge_graph_store import get_knowledge_graph_store
from app.db.memory_store import get_memory_store
from app.models.consolidation_agent import (
    ConsolidationRequest,
    ConsolidationResponse,
    EntityMergeSuggestion,
    StaleMemorySuggestion,
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


class ConsolidationAgent:
    """Propose duplicate-entity merges and stale-memory review candidates.

    This service is intentionally read-only. It never calls EntityMergeService,
    changes lifecycle state, or mutates trust. All proposed writes remain subject
    to an explicit user-approved action elsewhere in the product.
    """

    def __init__(self, settings: Settings) -> None:
        self._graph = get_knowledge_graph_store(settings)
        self._memories = get_memory_store(settings)

    def analyze(
        self,
        *,
        user_id: str,
        request: ConsolidationRequest,
    ) -> ConsolidationResponse:
        entities = self._graph.search_entities(
            user_id=user_id,
            query="",
            limit=request.entity_limit,
        )
        groups: dict[tuple[str, str], list] = defaultdict(list)
        for entity in entities:
            if entity.entity_type.value == "memory":
                continue
            key = _compact_name(entity.name)
            if not key:
                continue
            groups[(entity.entity_type.value, key)].append(entity)

        merge_suggestions: list[EntityMergeSuggestion] = []
        for (entity_type, _), group in sorted(groups.items()):
            if len(group) < 2:
                continue
            ordered = sorted(
                group,
                key=lambda e: (
                    -len(e.aliases),
                    len(e.name),
                    e.created_at,
                    e.entity_id,
                ),
            )
            target = ordered[0]
            for source in ordered[1:]:
                merge_suggestions.append(
                    EntityMergeSuggestion(
                        target_entity_id=target.entity_id,
                        target_name=target.name,
                        source_entity_id=source.entity_id,
                        source_name=source.name,
                        entity_type=entity_type,
                        reason="Names normalize to the same alphanumeric identity; merge requires explicit approval.",
                    )
                )

        stale: list[StaleMemorySuggestion] = []
        for memory in self._memories.list_recent(
            user_id=user_id,
            limit=request.memory_limit,
        ):
            trust = memory.trust
            if trust is None or trust.freshness >= request.stale_freshness_threshold:
                continue
            stale.append(
                StaleMemorySuggestion(
                    memory_id=memory.memory_id,
                    title=memory.title,
                    canonical_url=memory.canonical_url,
                    source_type=memory.source_type.value,
                    freshness=trust.freshness,
                    overall_trust=trust.overall,
                    reason=(
                        f"Persisted trust freshness {trust.freshness:.2f} is below "
                        f"the maintenance threshold {request.stale_freshness_threshold:.2f}; review before relying on it."
                    ),
                )
            )

        merge_suggestions.sort(
            key=lambda item: (
                item.entity_type,
                item.target_name.casefold(),
                item.source_name.casefold(),
                item.source_entity_id,
            )
        )
        stale.sort(key=lambda item: (item.freshness, item.overall_trust, item.memory_id))

        return ConsolidationResponse(
            proposed_merges=merge_suggestions[: request.result_limit],
            stale_memories=stale[: request.result_limit],
            merge_count=len(merge_suggestions),
            stale_count=len(stale),
            writes_performed=0,
        )


def _compact_name(value: str) -> str:
    return _NON_ALNUM.sub("", value.casefold())
