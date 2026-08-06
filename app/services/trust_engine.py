"""Trust Engine — compute and persist trust metrics for memories."""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import Settings, get_settings
from app.db.memory_store import MemoryStore, get_memory_store
from app.models.trust import TrustMetrics, TrustTier, VerificationStatus
from app.models.universal_memory import UniversalMemory
from app.models.video import SourceType


_SOURCE_RELIABILITY: dict[str, float] = {
    SourceType.YOUTUBE.value: 0.78,
    "web": 0.62,
    "article": 0.65,
    "readwise": 0.72,
}


class TrustEngine:
    """Foundation trust scoring for universal memory objects."""

    TRUSTED_THRESHOLD = 0.62
    MODERATE_THRESHOLD = 0.45

    def __init__(
        self,
        settings: Settings | None = None,
        store: MemoryStore | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._store = store or get_memory_store(self._settings)

    def compute(
        self,
        *,
        memory: UniversalMemory,
        chunk_count: int = 0,
        has_capsule: bool = False,
        user_helpful_feedback: bool | None = None,
        user_not_helpful_feedback: bool | None = None,
    ) -> TrustMetrics:
        now = datetime.now(timezone.utc).isoformat()
        source_key = memory.source_type.value if isinstance(memory.source_type, SourceType) else str(memory.source_type)
        source_reliability = _SOURCE_RELIABILITY.get(source_key, 0.55)

        freshness = self._freshness_score(memory.published_at, memory.updated_at)
        verification = self._verification_score(memory.verification_status)
        evidence_strength = self._evidence_strength(chunk_count, has_capsule)

        confidence = round(
            0.20 * source_reliability
            + 0.15 * freshness
            + 0.25 * verification
            + 0.40 * evidence_strength,
            4,
        )

        overall = confidence
        if user_helpful_feedback is True:
            overall = min(1.0, overall + 0.08)
        if user_not_helpful_feedback is True:
            overall = max(0.0, overall - 0.15)

        if memory.verification_status == VerificationStatus.DISPUTED:
            overall = min(overall, 0.35)

        overall = round(min(1.0, max(0.0, overall)), 4)
        tier = self._tier(overall, memory.verification_status)

        return TrustMetrics(
            source_reliability=round(source_reliability, 4),
            freshness=round(freshness, 4),
            verification=round(verification, 4),
            evidence_strength=round(evidence_strength, 4),
            confidence=confidence,
            overall=overall,
            tier=tier,
            computed_at=now,
            factors={
                "chunk_count": chunk_count,
                "has_capsule": has_capsule,
                "source_type": source_key,
                "verification_status": memory.verification_status.value,
            },
        )

    def score_and_persist(
        self,
        *,
        memory_id: str,
        user_id: str,
        chunk_count: int = 0,
        has_capsule: bool = False,
    ) -> TrustMetrics:
        memory = self._store.get(memory_id, user_id=user_id)
        if not memory:
            raise KeyError(f"Memory not found: {memory_id}")
        metrics = self.compute(memory=memory, chunk_count=chunk_count, has_capsule=has_capsule)
        self._store.upsert(
            user_id=user_id,
            source_type=memory.source_type,
            external_id=memory.external_id,
            canonical_url=memory.canonical_url,
            title=memory.title,
            source_author=memory.source_author,
            provenance=memory.provenance,
            metadata=memory.metadata,
            published_at=memory.published_at,
            lifecycle_state=memory.lifecycle_state,
            verification_status=memory.verification_status,
            embedding_refs=memory.embedding_refs,
            trust=metrics,
            relationship_summary=memory.relationship_summary,
        )
        return metrics

    def _freshness_score(self, published_at: str | None, updated_at: str) -> float:
        reference = published_at or updated_at
        try:
            ref_dt = datetime.fromisoformat(reference.replace("Z", "+00:00"))
            if ref_dt.tzinfo is None:
                ref_dt = ref_dt.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - ref_dt).days
        except (ValueError, TypeError):
            return 0.6
        if age_days <= 30:
            return 1.0
        if age_days <= 180:
            return 0.85
        if age_days <= 365:
            return 0.7
        if age_days <= 730:
            return 0.55
        return 0.4

    def _verification_score(self, status: VerificationStatus) -> float:
        return {
            VerificationStatus.UNVERIFIED: 0.2,
            VerificationStatus.PARTIAL: 0.55,
            VerificationStatus.VERIFIED: 0.92,
            VerificationStatus.DISPUTED: 0.1,
        }[status]

    def _evidence_strength(self, chunk_count: int, has_capsule: bool) -> float:
        if chunk_count <= 0:
            return 0.1
        chunk_component = min(1.0, chunk_count / 8.0)
        capsule_bonus = 0.15 if has_capsule else 0.0
        return min(1.0, chunk_component * 0.85 + capsule_bonus)

    def _tier(self, overall: float, verification: VerificationStatus) -> TrustTier:
        if verification == VerificationStatus.DISPUTED:
            return TrustTier.DISPUTED
        if overall >= self.TRUSTED_THRESHOLD:
            return TrustTier.TRUSTED
        if overall >= self.MODERATE_THRESHOLD:
            return TrustTier.MODERATE
        if overall >= 0.3:
            return TrustTier.SINGLE_SOURCE
        return TrustTier.LOW
