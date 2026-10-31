"""Synthetic-only identity continuity gates; no camera, faces or private frames."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.home_agent.instance_location import (
    InstanceObservation, derive_observed_location_changes,
)

BASE = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
_AUTO_ASSOCIATION = object()


def seen(instance, location, seconds, *, tenant="house-a", confidence=0.98,
         association=_AUTO_ASSOCIATION, obj="keys", evidence=None):
    return InstanceObservation(
        user_id=tenant, object_class=obj, location=location,
        observed_at=BASE + timedelta(seconds=seconds), source_id="camera-consented",
        evidence_id=evidence or f"frame-{instance}-{seconds}",
        instance_id=instance,
        identity_evidence_id=(f"proof-{tenant}-{instance}-{seconds}"
                              if association is _AUTO_ASSOCIATION else association),
        identity_confidence=confidence,
    )


def derive(rows):
    return derive_observed_location_changes(rows, user_id="house-a")


def test_two_identical_objects_in_different_rooms_do_not_fabricate_a_move():
    assert derive([seen("keys-1", "desk", 0), seen("keys-2", "kitchen", 30)]) == []


def test_same_evidenced_instance_reports_observed_change_with_both_provenances():
    changes = derive([seen("keys-1", "desk", 0, association="match-a"),
                      seen("keys-1", "kitchen", 30, association="match-b")])
    assert len(changes) == 1
    change = changes[0]
    assert (change.from_location, change.to_location) == ("desk", "kitchen")
    assert (change.from_identity_evidence_id, change.to_identity_evidence_id) == ("match-a", "match-b")
    assert change.last_seen_from == BASE
    assert change.first_seen_to == BASE + timedelta(seconds=30)
    assert not hasattr(change, "mover_id")


def test_unknown_identity_or_missing_provenance_cannot_create_transition():
    assert derive([seen(None, "desk", 0), seen(None, "kitchen", 30)]) == []
    assert derive([seen("keys-1", "desk", 0),
                   seen("keys-1", "kitchen", 30, association=None)]) == []
    assert derive([seen("keys-1", "desk", 0, confidence=0.4),
                   seen("keys-1", "kitchen", 30)]) == []


def test_conflicting_same_instance_simultaneous_locations_break_continuity():
    assert derive([seen("keys-1", "desk", 0),
                   seen("keys-1", "desk", 10),
                   seen("keys-1", "kitchen", 10),
                   seen("keys-1", "kitchen", 20)]) == []


def test_cross_tenant_instance_ids_never_join():
    assert derive([seen("keys-1", "desk", 0, tenant="house-a"),
                   seen("keys-1", "kitchen", 30, tenant="house-b")]) == []


def test_blind_gap_and_class_conflict_break_continuity():
    assert derive([seen("keys-1", "desk", 0),
                   seen("keys-1", "kitchen", 301)]) == []
    assert derive([seen("keys-1", "desk", 0),
                   seen("keys-1", "kitchen", 30, obj="phone")]) == []


def test_repeated_same_location_does_not_create_transition():
    assert derive([seen("keys-1", "desk", 0), seen("keys-1", "desk", 30)]) == []


def test_reordered_input_produces_identical_evidence_chain():
    rows = [seen("keys-1", "desk", 0), seen("keys-1", "kitchen", 30)]
    assert derive(rows) == derive(list(reversed(rows)))


@pytest.mark.parametrize("confidence", [float("nan"), float("inf"), -0.1, 1.1, True])
def test_invalid_identity_confidence_is_rejected(confidence):
    with pytest.raises(ValueError, match="identity_confidence"):
        seen("keys-1", "desk", 0, confidence=confidence)


def test_naive_timestamp_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        InstanceObservation("house-a", "keys", "desk", BASE.replace(tzinfo=None),
                            "camera", "frame", "keys-1", "proof", 0.99)


def test_invalid_gap_is_rejected():
    with pytest.raises(ValueError, match="max_gap"):
        derive_observed_location_changes([], user_id="house-a", max_gap=timedelta(hours=1))


def test_reused_evidence_across_distinct_instances_invalidates_both_chains():
    rows = [
        seen("keys-1", "desk", 0, evidence="reused-frame"),
        seen("keys-2", "desk", 0, evidence="reused-frame"),
        seen("keys-1", "kitchen", 30, evidence="unique-frame"),
    ]
    assert derive(rows) == []
    assert derive(list(reversed(rows))) == []


def test_reused_identity_proof_for_two_instances_invalidates_both_chains():
    # Distinct observation IDs are insufficient when the identity verifier's
    # proof ID is claimed for two different physical objects in one household.
    rows = [
        seen("keys-1", "desk", 0, association="shared-proof"),
        seen("keys-2", "hallway", 10, association="shared-proof"),
        seen("keys-1", "kitchen", 30, association="unique-proof"),
    ]
    assert derive(rows) == []
    assert derive(list(reversed(rows))) == []


def test_replayed_identity_proof_for_same_instance_is_not_new_evidence():
    # One proof cannot authenticate two different sightings, even when the
    # verifier labels both as the same instance. Order must not matter.
    rows = [
        seen("keys-1", "desk", 0, association="replayed-proof"),
        seen("keys-1", "kitchen", 30, association="replayed-proof"),
    ]
    assert derive(rows) == []
    assert derive(list(reversed(rows))) == []


def test_unknown_instance_replaying_proof_breaks_known_identity_chain():
    # An unverified/unknown object must not be able to reuse a proof that
    # otherwise authenticates a different sighting of a known instance.
    rows = [
        seen("keys-1", "desk", 0, association="shared-proof"),
        seen(None, "hallway", 10, association="shared-proof"),
        seen("keys-1", "kitchen", 30, association="unique-proof"),
    ]
    assert derive(rows) == []
    assert derive(list(reversed(rows))) == []


def test_unknown_instance_proof_collision_in_another_tenant_is_isolated():
    rows = [
        seen("keys-1", "desk", 0, association="shared-proof"),
        seen(None, "hallway", 10, tenant="house-b", association="shared-proof"),
        seen("keys-1", "kitchen", 30, association="unique-proof"),
    ]
    assert len(derive(rows)) == 1


def test_identity_proof_ids_are_scoped_to_tenant_not_globally_unique():
    rows = [
        seen("keys-1", "desk", 0, association="shared-proof"),
        seen("keys-2", "hallway", 10, tenant="house-b", association="shared-proof"),
        seen("keys-1", "kitchen", 30, association="unique-proof"),
    ]
    changes = derive(rows)
    assert len(changes) == 1
    assert changes[0].instance_id == "keys-1"
    assert (changes[0].from_location, changes[0].to_location) == ("desk", "kitchen")


def test_reused_evidence_at_different_times_breaks_continuity():
    rows = [
        seen("keys-1", "desk", 0, evidence="reused-frame"),
        seen("keys-1", "desk", 10, evidence="reused-frame"),
        seen("keys-1", "kitchen", 20, evidence="unique-frame"),
    ]
    assert derive(rows) == []


@pytest.mark.parametrize(("field", "bad"), [
    ("instance_id", 123), ("instance_id", ""), ("instance_id", "  "),
    ("identity_evidence_id", 123), ("identity_evidence_id", ""),
    ("identity_evidence_id", "  "),
])
def test_invalid_optional_identity_fields_are_rejected(field, bad):
    kwargs = {
        "user_id": "house-a", "object_class": "keys", "location": "desk",
        "observed_at": BASE, "source_id": "camera", "evidence_id": "frame",
        "instance_id": "keys-1", "identity_evidence_id": "proof",
        "identity_confidence": 0.99,
    }
    kwargs[field] = bad
    with pytest.raises(ValueError, match=field):
        InstanceObservation(**kwargs)


def test_malformed_record_and_timestamp_fail_explicitly():
    with pytest.raises(ValueError, match="InstanceObservation"):
        derive([seen("keys-1", "desk", 0), object()])
    with pytest.raises(ValueError, match="timezone-aware"):
        InstanceObservation("house-a", "keys", "desk", "not-a-date",
                            "camera", "frame", "keys-1", "proof", 0.99)
