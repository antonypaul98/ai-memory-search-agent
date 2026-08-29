"""Phase 4 Consolidation Agent regression tests."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.db.knowledge_graph_store import get_knowledge_graph_store
from app.db.memory_store import get_memory_store
from app.models.consolidation_agent import ConsolidationRequest
from app.models.knowledge_graph import EntityType
from app.models.trust import TrustMetrics, TrustTier
from app.models.user import LOCAL_DEFAULT_USER_ID
from app.models.video import SourceType
from app.services.consolidation_agent import ConsolidationAgent


def _trust(*, freshness: float, overall: float) -> TrustMetrics:
    return TrustMetrics(
        source_reliability=0.8,
        freshness=freshness,
        verification=0.8,
        evidence_strength=0.8,
        confidence=overall,
        overall=overall,
        tier=TrustTier.MODERATE,
        computed_at=datetime.now(timezone.utc).isoformat(),
    )


def test_proposes_same_type_compact_name_merge_without_writing(test_settings: Settings) -> None:
    store = get_knowledge_graph_store(test_settings)
    target = store.upsert_entity(
        user_id=LOCAL_DEFAULT_USER_ID,
        entity_type=EntityType.COMPANY,
        name="OpenAI",
    )
    source = store.upsert_entity(
        user_id=LOCAL_DEFAULT_USER_ID,
        entity_type=EntityType.COMPANY,
        name="Open AI",
    )

    out = ConsolidationAgent(test_settings).analyze(
        user_id=LOCAL_DEFAULT_USER_ID,
        request=ConsolidationRequest(),
    )
    assert out.merge_count == 1
    suggestion = out.proposed_merges[0]
    assert suggestion.target_entity_id == target.entity_id
    assert suggestion.source_entity_id == source.entity_id
    assert suggestion.entity_type == "company"
    assert out.writes_performed == 0
    # Analysis must not perform the proposed merge.
    assert store.get_entity(target.entity_id, user_id=LOCAL_DEFAULT_USER_ID) is not None
    assert store.get_entity(source.entity_id, user_id=LOCAL_DEFAULT_USER_ID) is not None


def test_does_not_merge_cross_type_or_cross_tenant_entities(test_settings: Settings) -> None:
    store = get_knowledge_graph_store(test_settings)
    store.upsert_entity(
        user_id="user-a",
        entity_type=EntityType.COMPANY,
        name="Acme Inc",
    )
    store.upsert_entity(
        user_id="user-a",
        entity_type=EntityType.PROJECT,
        name="AcmeInc",
    )
    store.upsert_entity(
        user_id="user-b",
        entity_type=EntityType.COMPANY,
        name="AcmeInc",
    )
    out = ConsolidationAgent(test_settings).analyze(
        user_id="user-a",
        request=ConsolidationRequest(),
    )
    assert out.proposed_merges == []


def test_flags_only_tenant_stale_trust_memories(test_settings: Settings) -> None:
    store = get_memory_store(test_settings)
    stale = store.upsert(
        user_id="user-a",
        source_type=SourceType.WEB,
        external_id="stale",
        canonical_url="https://example.com/stale",
        title="Old guidance",
        trust=_trust(freshness=0.2, overall=0.6),
    )
    store.upsert(
        user_id="user-a",
        source_type=SourceType.WEB,
        external_id="fresh",
        canonical_url="https://example.com/fresh",
        title="Fresh guidance",
        trust=_trust(freshness=0.9, overall=0.8),
    )
    store.upsert(
        user_id="user-b",
        source_type=SourceType.WEB,
        external_id="secret",
        canonical_url="https://example.com/secret",
        title="Secret stale guidance",
        trust=_trust(freshness=0.1, overall=0.5),
    )

    out = ConsolidationAgent(test_settings).analyze(
        user_id="user-a",
        request=ConsolidationRequest(stale_freshness_threshold=0.5),
    )
    assert out.stale_count == 1
    assert out.stale_memories[0].memory_id == stale.memory_id
    assert "Secret" not in str(out.model_dump())
    assert out.writes_performed == 0


def test_consolidation_api_uses_authenticated_user(client: TestClient, test_settings: Settings) -> None:
    store = get_knowledge_graph_store(test_settings)
    store.upsert_entity(
        user_id=LOCAL_DEFAULT_USER_ID,
        entity_type=EntityType.TECHNOLOGY,
        name="Postgres",
    )
    store.upsert_entity(
        user_id=LOCAL_DEFAULT_USER_ID,
        entity_type=EntityType.TECHNOLOGY,
        name="Post gres",
    )
    store.upsert_entity(
        user_id="other",
        entity_type=EntityType.COMPANY,
        name="Private Corp",
    )
    store.upsert_entity(
        user_id="other",
        entity_type=EntityType.COMPANY,
        name="PrivateCorp",
    )

    resp = client.post("/api/v1/agents/consolidation/analyze", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["merge_count"] == 1
    assert body["writes_performed"] == 0
    assert "Private" not in str(body)


def test_consolidation_merge_requires_explicit_confirmation_then_applies(
    client: TestClient,
    test_settings: Settings,
) -> None:
    store = get_knowledge_graph_store(test_settings)
    target = store.upsert_entity(
        user_id=LOCAL_DEFAULT_USER_ID,
        entity_type=EntityType.COMPANY,
        name="OpenAI",
    )
    source = store.upsert_entity(
        user_id=LOCAL_DEFAULT_USER_ID,
        entity_type=EntityType.COMPANY,
        name="Open AI",
    )

    analysis = client.post("/api/v1/agents/consolidation/analyze", json={})
    assert analysis.status_code == 200
    assert analysis.json()["writes_performed"] == 0
    assert store.get_entity(source.entity_id, user_id=LOCAL_DEFAULT_USER_ID) is not None

    missing_confirmation = client.post(
        "/api/v1/agents/consolidation/approve-merge",
        json={
            "target_entity_id": target.entity_id,
            "source_entity_id": source.entity_id,
        },
    )
    assert missing_confirmation.status_code == 422
    assert store.get_entity(source.entity_id, user_id=LOCAL_DEFAULT_USER_ID) is not None

    denied_confirmation = client.post(
        "/api/v1/agents/consolidation/approve-merge",
        json={
            "target_entity_id": target.entity_id,
            "source_entity_id": source.entity_id,
            "confirm": False,
        },
    )
    assert denied_confirmation.status_code == 422
    assert store.get_entity(source.entity_id, user_id=LOCAL_DEFAULT_USER_ID) is not None

    approved = client.post(
        "/api/v1/agents/consolidation/approve-merge",
        json={
            "target_entity_id": target.entity_id,
            "source_entity_id": source.entity_id,
            "confirm": True,
        },
    )
    assert approved.status_code == 200
    assert approved.json()["merged_source_entity_id"] == source.entity_id
    assert store.get_entity(source.entity_id, user_id=LOCAL_DEFAULT_USER_ID) is None
    assert store.get_entity(target.entity_id, user_id=LOCAL_DEFAULT_USER_ID) is not None


def test_consolidation_merge_approval_cannot_cross_tenant(
    client: TestClient,
    test_settings: Settings,
) -> None:
    store = get_knowledge_graph_store(test_settings)
    target = store.upsert_entity(
        user_id=LOCAL_DEFAULT_USER_ID,
        entity_type=EntityType.COMPANY,
        name="Acme",
    )
    other_source = store.upsert_entity(
        user_id="other",
        entity_type=EntityType.COMPANY,
        name="Acme Inc",
    )

    response = client.post(
        "/api/v1/agents/consolidation/approve-merge",
        json={
            "target_entity_id": target.entity_id,
            "source_entity_id": other_source.entity_id,
            "confirm": True,
        },
    )
    assert response.status_code == 404
    assert store.get_entity(other_source.entity_id, user_id="other") is not None
