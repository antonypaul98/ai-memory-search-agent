"""Synthetic-only query integration; no camera or biometric input."""
from datetime import datetime, timedelta, timezone

import pytest

from app.models.user import UserPublic
from app.services.home_agent.authenticated_query import AuthenticatedHomeAgentQuery
from app.services.home_agent.instance_location import InstanceObservation
from app.services.home_agent.query_service import HomeAgentQueryService

NOW = datetime(2026, 10, 25, 18, 0, tzinfo=timezone.utc)


def sighting(instance_id, location, seconds, *, tenant="house-a", obj="keys",
             proof="verified-match", confidence=0.99):
    return InstanceObservation(
        user_id=tenant, object_class=obj, location=location,
        observed_at=NOW + timedelta(seconds=seconds),
        source_id="consented-camera", evidence_id=f"frame-{instance_id}-{seconds}",
        instance_id=instance_id, identity_evidence_id=proof,
        identity_confidence=confidence,
    )


class VerifiedStore:
    def __init__(self, observations):
        self.observations = observations
        self.calls = []

    def verified_instance_observations(self, **kwargs):
        self.calls.append(kwargs)
        return self.observations


def test_legacy_class_only_store_cannot_claim_verified_location_changes():
    class LegacyStore:
        def history(self, **kwargs):
            raise AssertionError("class-only history must never be used")
    assert HomeAgentQueryService(LegacyStore()).observed_location_changes(
        user_id="house-a", object_name="keys"
    ) == []


def test_two_distinct_keys_do_not_create_a_relocation():
    store = VerifiedStore([sighting("keys-1", "desk", 0),
                           sighting("keys-2", "kitchen", 30)])
    service = HomeAgentQueryService(store)
    assert service.observed_location_changes(
        user_id="house-a", object_name="keys", limit=8
    ) == []
    assert store.calls == [{"user_id": "house-a", "object_name": "keys",
                            "min_confidence": 0.9, "limit": 8}]


def test_verified_instance_change_retains_both_evidence_ids():
    store = VerifiedStore([sighting("keys-1", "desk", 0, proof="match-1"),
                           sighting("keys-1", "kitchen", 30, proof="match-2")])
    result = HomeAgentQueryService(store).observed_location_changes(
        user_id="house-a", object_name="keys"
    )
    assert len(result) == 1
    assert (result[0].from_location, result[0].to_location) == ("desk", "kitchen")
    assert (result[0].from_identity_evidence_id,
            result[0].to_identity_evidence_id) == ("match-1", "match-2")
    assert not hasattr(result[0], "mover_id")


@pytest.mark.parametrize("rows", [
    [sighting("keys-1", "desk", 0), sighting("keys-1", "kitchen", 30, proof=None)],
    [sighting("keys-1", "desk", 0), sighting("keys-1", "kitchen", 301)],
    [sighting("keys-1", "desk", 0), sighting("keys-1", "kitchen", 30, confidence=0.5)],
    [sighting("keys-1", "desk", 0), sighting("keys-1", "kitchen", 30, tenant="house-b")],
    [sighting("keys-1", "desk", 0), sighting("keys-1", "kitchen", 30, obj="phone")],
    [sighting("keys-1", "desk", 0), object()],
])
def test_uncertain_or_out_of_scope_chain_fails_closed(rows):
    assert HomeAgentQueryService(VerifiedStore(rows)).observed_location_changes(
        user_id="house-a", object_name="keys"
    ) == []


def test_authenticated_boundary_uses_session_tenant_not_caller_input():
    store = VerifiedStore([sighting("keys-1", "desk", 0),
                           sighting("keys-1", "kitchen", 30)])
    boundary = AuthenticatedHomeAgentQuery(
        service=HomeAgentQueryService(store),
        user=UserPublic(user_id="house-a"),
    )
    assert len(boundary.observed_location_changes(object_name="keys")) == 1
    assert store.calls[0]["user_id"] == "house-a"
    with pytest.raises(TypeError):
        boundary.observed_location_changes(user_id="house-b", object_name="keys")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, 1.1, True])
def test_invalid_min_confidence_is_rejected_before_store_access(bad):
    store = VerifiedStore([])
    with pytest.raises(ValueError, match="min_confidence"):
        HomeAgentQueryService(store).observed_location_changes(
            user_id="house-a", object_name="keys", min_confidence=bad
        )
    assert store.calls == []
