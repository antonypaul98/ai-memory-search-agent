"""Phase 4 Capture Triage Agent: validate, canonicalize, and dedupe capture queues."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.models.capture_triage import (
    CaptureTriageDecision,
    CaptureTriageRequest,
    CaptureTriageResponse,
)
from app.services.cross_duplicate_service import CrossConnectorDuplicateDetector
from app.services.deduplication_service import hash_text
from app.services.sources import get_connector_registry


class CaptureTriageAgent:
    """Produce deterministic, tenant-scoped ingest decisions without side effects.

    The triage pass performs no network fetches and no writes. URL validation and
    canonicalization are delegated to the registered connectors, which preserves
    existing SSRF/scheme restrictions. Existing-memory checks use the tenant-scoped
    cross-connector canonical URL index.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._connectors = get_connector_registry()
        self._dupes = CrossConnectorDuplicateDetector(self._settings)

    def triage(self, *, user_id: str, request: CaptureTriageRequest) -> CaptureTriageResponse:
        user_id = (user_id or "").strip()
        if not user_id:
            raise ValueError("user_id is required")

        seen: dict[str, int] = {}
        decisions: list[CaptureTriageDecision] = []

        for index, item in enumerate(request.items):
            original = item.url.strip()
            try:
                connector = self._connectors.resolve_for_url(original)
                ref = connector.parse_ref(original)
                canonical = ref.url.strip()
                if not canonical:
                    raise ValueError("connector returned an empty canonical URL")
            except Exception as exc:
                decisions.append(
                    CaptureTriageDecision(
                        index=index,
                        original_url=original,
                        decision="rejected",
                        reason=f"Unsupported or unsafe URL: {exc}",
                    )
                )
                continue

            key = hash_text(canonical)
            if key in seen:
                first_index = seen[key]
                decisions.append(
                    CaptureTriageDecision(
                        index=index,
                        original_url=original,
                        canonical_url=canonical,
                        connector_id=connector.connector_id,
                        decision="duplicate",
                        reason="Duplicate canonical URL in this capture batch.",
                        duplicate_of_index=first_index,
                    )
                )
                continue
            seen[key] = index

            existing = self._dupes.check(user_id=user_id, canonical_url=canonical)
            if existing.is_duplicate:
                decisions.append(
                    CaptureTriageDecision(
                        index=index,
                        original_url=original,
                        canonical_url=canonical,
                        connector_id=connector.connector_id,
                        decision="duplicate",
                        reason=existing.reason or "Already present in Memory.",
                    )
                )
                continue

            decisions.append(
                CaptureTriageDecision(
                    index=index,
                    original_url=original,
                    canonical_url=canonical,
                    connector_id=connector.connector_id,
                    decision="ready",
                    reason="Validated and ready for capture.",
                )
            )

        ready = sum(d.decision == "ready" for d in decisions)
        duplicates = sum(d.decision == "duplicate" for d in decisions)
        rejected = sum(d.decision == "rejected" for d in decisions)
        return CaptureTriageResponse(
            total=len(decisions),
            ready=ready,
            duplicates=duplicates,
            rejected=rejected,
            decisions=decisions,
        )

    def ready_items(self, request: CaptureTriageRequest, result: CaptureTriageResponse):
        """Return original typed capture items corresponding to ready decisions."""
        ready_indexes = {d.index for d in result.decisions if d.decision == "ready"}
        return [item for index, item in enumerate(request.items) if index in ready_indexes]
