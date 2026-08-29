"""A-02 Ingest Agent: approved deterministic rules over the canonical ingest pipeline."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from app.config import Settings, get_settings
from app.db.schema import get_connection
from app.models.ingest_agent import (
    IngestAgentDecision,
    IngestAgentRunResponse,
    IngestCandidate,
    IngestRule,
    IngestRuleCreate,
)
from app.services.deduplication_service import hash_text
from app.services.event_bus import EventBus
from app.services.ingest_service import IngestService
from app.services.sources import get_connector_registry


class IngestAgent:
    """Execute only explicitly approved, tenant-scoped auto-ingest rules.

    Rules are intentionally deterministic. Candidate URLs are resolved through the
    registered connector SDK, so connector URL validation/canonicalization remains
    authoritative. Successful rule executions always reuse ``IngestService`` and
    therefore preserve existing provenance, deduplication, evidence, and privacy
    behavior.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._events = EventBus(self._settings)
        self._connectors = get_connector_registry()
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        with get_connection(self._settings) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS ingest_agent_rules (
                    rule_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    connector_id TEXT NOT NULL,
                    match_json TEXT NOT NULL DEFAULT '{}',
                    force_refresh INTEGER NOT NULL DEFAULT 0,
                    approved INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ingest_agent_rules_user
                    ON ingest_agent_rules(user_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS ingest_agent_claims (
                    user_id TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    canonical_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, rule_id, canonical_hash)
                );
                """
            )

    def create_rule(self, *, user_id: str, request: IngestRuleCreate) -> IngestRule:
        user_id = self._require_user(user_id)
        rule_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        normalized_match = {
            str(key).strip(): str(value).strip()
            for key, value in request.match.items()
            if str(key).strip() and str(value).strip()
        }
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                INSERT INTO ingest_agent_rules (
                    rule_id, user_id, name, connector_id, match_json, force_refresh,
                    approved, enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
                """,
                (
                    rule_id,
                    user_id,
                    request.name.strip(),
                    request.connector_id.strip(),
                    json.dumps(normalized_match, sort_keys=True),
                    int(request.force_refresh),
                    now,
                    now,
                ),
            )
        self._events.emit(
            user_id=user_id,
            event_type="agent.ingest_rule.created",
            aggregate_type="ingest_rule",
            aggregate_id=rule_id,
            actor="user",
            payload={"connector_id": request.connector_id.strip(), "approved": False},
        )
        return self.get_rule(user_id=user_id, rule_id=rule_id)

    def approve_rule(self, *, user_id: str, rule_id: str) -> IngestRule:
        user_id = self._require_user(user_id)
        now = datetime.now(timezone.utc).isoformat()
        with get_connection(self._settings) as conn:
            cur = conn.execute(
                """
                UPDATE ingest_agent_rules
                SET approved = 1, enabled = 1, updated_at = ?
                WHERE rule_id = ? AND user_id = ?
                """,
                (now, rule_id, user_id),
            )
            if cur.rowcount != 1:
                raise KeyError("ingest rule not found")
        self._events.emit(
            user_id=user_id,
            event_type="agent.ingest_rule.approved",
            aggregate_type="ingest_rule",
            aggregate_id=rule_id,
            actor="user",
            payload={"enabled": True},
        )
        return self.get_rule(user_id=user_id, rule_id=rule_id)

    def disable_rule(self, *, user_id: str, rule_id: str) -> IngestRule:
        user_id = self._require_user(user_id)
        with get_connection(self._settings) as conn:
            cur = conn.execute(
                """
                UPDATE ingest_agent_rules
                SET enabled = 0, updated_at = ?
                WHERE rule_id = ? AND user_id = ?
                """,
                (datetime.now(timezone.utc).isoformat(), rule_id, user_id),
            )
            if cur.rowcount != 1:
                raise KeyError("ingest rule not found")
        return self.get_rule(user_id=user_id, rule_id=rule_id)

    def get_rule(self, *, user_id: str, rule_id: str) -> IngestRule:
        user_id = self._require_user(user_id)
        with get_connection(self._settings) as conn:
            row = conn.execute(
                "SELECT * FROM ingest_agent_rules WHERE rule_id = ? AND user_id = ?",
                (rule_id, user_id),
            ).fetchone()
        if row is None:
            raise KeyError("ingest rule not found")
        return IngestRule(
            rule_id=row["rule_id"],
            name=row["name"],
            connector_id=row["connector_id"],
            match=json.loads(row["match_json"] or "{}"),
            force_refresh=bool(row["force_refresh"]),
            approved=bool(row["approved"]),
            enabled=bool(row["enabled"]),
        )

    def run_rule(
        self,
        *,
        user_id: str,
        rule_id: str,
        candidates: list[IngestCandidate],
    ) -> IngestAgentRunResponse:
        user_id = self._require_user(user_id)
        rule = self.get_rule(user_id=user_id, rule_id=rule_id)
        if not rule.approved or not rule.enabled:
            raise PermissionError("ingest rule requires explicit user approval and must be enabled")
        if not candidates:
            raise ValueError("at least one ingest candidate is required")
        if len(candidates) > 100:
            raise ValueError("ingest rule run is limited to 100 candidates")

        decisions: list[IngestAgentDecision] = []
        for index, candidate in enumerate(candidates):
            original_url = candidate.url.strip()
            try:
                connector = self._connectors.resolve_for_url(original_url)
                ref = connector.parse_ref(original_url)
                canonical_url = ref.url.strip()
                if not canonical_url:
                    raise ValueError("connector returned an empty canonical URL")
            except Exception as exc:
                decisions.append(
                    IngestAgentDecision(
                        index=index,
                        decision="rejected",
                        reason=f"Unsupported or unsafe URL: {exc}",
                    )
                )
                continue

            if connector.connector_id != rule.connector_id:
                decisions.append(
                    IngestAgentDecision(
                        index=index,
                        decision="skipped",
                        reason="Candidate connector does not match the approved rule.",
                        canonical_url=canonical_url,
                    )
                )
                continue

            if any(candidate.attributes.get(key) != value for key, value in rule.match.items()):
                decisions.append(
                    IngestAgentDecision(
                        index=index,
                        decision="skipped",
                        reason="Candidate metadata does not match the approved rule.",
                        canonical_url=canonical_url,
                    )
                )
                continue

            claim_hash = hash_text(canonical_url)
            if not self._claim(user_id=user_id, rule_id=rule_id, canonical_hash=claim_hash):
                decisions.append(
                    IngestAgentDecision(
                        index=index,
                        decision="duplicate",
                        reason="This canonical URL was already claimed by the rule.",
                        canonical_url=canonical_url,
                    )
                )
                continue

            try:
                IngestService(self._settings).ingest_single_url(
                    canonical_url,
                    user_id=user_id,
                    force_refresh=rule.force_refresh,
                )
            except Exception as exc:
                self._release_claim(user_id=user_id, rule_id=rule_id, canonical_hash=claim_hash)
                decisions.append(
                    IngestAgentDecision(
                        index=index,
                        decision="failed",
                        reason=f"Ingest failed: {type(exc).__name__}",
                        canonical_url=canonical_url,
                    )
                )
                continue

            self._complete_claim(user_id=user_id, rule_id=rule_id, canonical_hash=claim_hash)
            decisions.append(
                IngestAgentDecision(
                    index=index,
                    decision="ingested",
                    reason="Matched approved rule and was ingested through the canonical pipeline.",
                    canonical_url=canonical_url,
                )
            )

        counts = {name: sum(d.decision == name for d in decisions) for name in (
            "ingested", "duplicate", "skipped", "rejected", "failed"
        )}
        self._events.emit(
            user_id=user_id,
            event_type="agent.ingest_rule.completed",
            aggregate_type="ingest_rule",
            aggregate_id=rule_id,
            actor="agent:ingest",
            payload={"total": len(decisions), **counts},
        )
        return IngestAgentRunResponse(
            rule_id=rule_id,
            total=len(decisions),
            ingested=counts["ingested"],
            duplicates=counts["duplicate"],
            skipped=counts["skipped"],
            rejected=counts["rejected"],
            failed=counts["failed"],
            decisions=decisions,
            metadata={"connector_id": rule.connector_id},
        )

    def _claim(self, *, user_id: str, rule_id: str, canonical_hash: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with get_connection(self._settings) as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO ingest_agent_claims (
                    user_id, rule_id, canonical_hash, status, updated_at
                ) VALUES (?, ?, ?, 'processing', ?)
                """,
                (user_id, rule_id, canonical_hash, now),
            )
            return cur.rowcount == 1

    def _complete_claim(self, *, user_id: str, rule_id: str, canonical_hash: str) -> None:
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                UPDATE ingest_agent_claims SET status = 'completed', updated_at = ?
                WHERE user_id = ? AND rule_id = ? AND canonical_hash = ?
                """,
                (datetime.now(timezone.utc).isoformat(), user_id, rule_id, canonical_hash),
            )

    def _release_claim(self, *, user_id: str, rule_id: str, canonical_hash: str) -> None:
        with get_connection(self._settings) as conn:
            conn.execute(
                """
                DELETE FROM ingest_agent_claims
                WHERE user_id = ? AND rule_id = ? AND canonical_hash = ?
                """,
                (user_id, rule_id, canonical_hash),
            )

    @staticmethod
    def _require_user(user_id: str) -> str:
        user_id = (user_id or "").strip()
        if not user_id:
            raise ValueError("user_id is required")
        return user_id
