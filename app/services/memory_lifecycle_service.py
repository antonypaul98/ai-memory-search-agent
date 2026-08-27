"""Memory lifecycle state machine and transition enforcement."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.db.memory_store import MemoryStore, get_memory_store
from app.models.lifecycle import INGEST_PIPELINE, MemoryLifecycleState
from app.models.universal_memory import UniversalMemory


# Valid transitions: from_state -> set of allowed to_states
_ALLOWED_TRANSITIONS: dict[MemoryLifecycleState, set[MemoryLifecycleState]] = {
    MemoryLifecycleState.CAPTURED: {
        MemoryLifecycleState.PARSED,
        MemoryLifecycleState.ARCHIVED,
    },
    MemoryLifecycleState.PARSED: {
        MemoryLifecycleState.ENRICHED,
        MemoryLifecycleState.ARCHIVED,
    },
    MemoryLifecycleState.ENRICHED: {
        MemoryLifecycleState.EMBEDDED,
        MemoryLifecycleState.ARCHIVED,
    },
    MemoryLifecycleState.EMBEDDED: {
        MemoryLifecycleState.CONNECTED,
        MemoryLifecycleState.ARCHIVED,
    },
    MemoryLifecycleState.CONNECTED: {
        MemoryLifecycleState.VERIFIED,
        MemoryLifecycleState.ARCHIVED,
    },
    MemoryLifecycleState.VERIFIED: {
        MemoryLifecycleState.TRUSTED,
        MemoryLifecycleState.ARCHIVED,
    },
    MemoryLifecycleState.TRUSTED: {
        MemoryLifecycleState.MERGED,
        MemoryLifecycleState.ARCHIVED,
    },
    MemoryLifecycleState.MERGED: {
        MemoryLifecycleState.ARCHIVED,
        MemoryLifecycleState.TRUSTED,
    },
    MemoryLifecycleState.ARCHIVED: {
        MemoryLifecycleState.REVIVED,
    },
    MemoryLifecycleState.REVIVED: {
        MemoryLifecycleState.PARSED,
        MemoryLifecycleState.ENRICHED,
        MemoryLifecycleState.ARCHIVED,
    },
}


class InvalidLifecycleTransitionError(ValueError):
    """Raised when a lifecycle transition is not permitted."""


class MemoryLifecycleService:
    """Enforces lifecycle transitions with audit trail."""

    def __init__(
        self,
        settings: Settings | None = None,
        store: MemoryStore | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._store = store or get_memory_store(self._settings)

    def can_transition(
        self,
        from_state: MemoryLifecycleState,
        to_state: MemoryLifecycleState,
    ) -> bool:
        if from_state == to_state:
            return True
        allowed = _ALLOWED_TRANSITIONS.get(from_state, set())
        return to_state in allowed

    def transition(
        self,
        *,
        memory_id: str,
        user_id: str,
        to_state: MemoryLifecycleState,
        reason: str = "",
        actor: str = "system",
        metadata: dict | None = None,
        force: bool = False,
    ) -> UniversalMemory:
        memory = self._store.get(memory_id, user_id=user_id)
        if not memory:
            raise KeyError(f"Memory not found: {memory_id}")
        if not force and not self.can_transition(memory.lifecycle_state, to_state):
            raise InvalidLifecycleTransitionError(
                f"Cannot transition {memory.lifecycle_state.value} -> {to_state.value}"
            )
        if memory.lifecycle_state == to_state:
            return memory
        return self._store.update_lifecycle_state(
            memory_id=memory_id,
            user_id=user_id,
            from_state=memory.lifecycle_state,
            to_state=to_state,
            reason=reason,
            actor=actor,
            metadata=metadata,
        )

    def advance_pipeline(
        self,
        *,
        memory_id: str,
        user_id: str,
        target_state: MemoryLifecycleState,
        reason: str = "",
        actor: str = "system",
    ) -> UniversalMemory:
        """Advance through ingest pipeline states in order up to target_state."""
        memory = self._store.get(memory_id, user_id=user_id)
        if not memory:
            raise KeyError(f"Memory not found: {memory_id}")

        if target_state not in INGEST_PIPELINE:
            return self.transition(
                memory_id=memory_id,
                user_id=user_id,
                to_state=target_state,
                reason=reason,
                actor=actor,
            )

        current_idx = -1
        try:
            current_idx = INGEST_PIPELINE.index(memory.lifecycle_state)
        except ValueError:
            current_idx = -1

        target_idx = INGEST_PIPELINE.index(target_state)
        updated = memory
        for state in INGEST_PIPELINE[current_idx + 1 : target_idx + 1]:
            updated = self.transition(
                memory_id=memory_id,
                user_id=user_id,
                to_state=state,
                reason=reason or f"pipeline:{state.value}",
                actor=actor,
            )
        return updated

    def archive(self, *, memory_id: str, user_id: str, reason: str = "") -> UniversalMemory:
        return self.transition(
            memory_id=memory_id,
            user_id=user_id,
            to_state=MemoryLifecycleState.ARCHIVED,
            reason=reason or "archived",
            actor="user",
        )

    def revive(self, *, memory_id: str, user_id: str, reason: str = "") -> UniversalMemory:
        return self.transition(
            memory_id=memory_id,
            user_id=user_id,
            to_state=MemoryLifecycleState.REVIVED,
            reason=reason or "revived",
            actor="user",
        )

    def merge(
        self,
        *,
        memory_id: str,
        user_id: str,
        into_memory_id: str,
        reason: str = "",
        actor: str = "system",
    ) -> UniversalMemory:
        """Mark a trusted memory as merged into another trusted memory."""
        target = self._store.get(into_memory_id, user_id=user_id)
        if not target:
            raise KeyError(f"Target memory not found: {into_memory_id}")
        if target.lifecycle_state != MemoryLifecycleState.TRUSTED:
            raise InvalidLifecycleTransitionError(
                f"Merge target must be trusted, got {target.lifecycle_state.value}"
            )
        return self.transition(
            memory_id=memory_id,
            user_id=user_id,
            to_state=MemoryLifecycleState.MERGED,
            reason=reason or f"merged_into:{into_memory_id}",
            actor=actor,
            metadata={"into_memory_id": into_memory_id},
        )
