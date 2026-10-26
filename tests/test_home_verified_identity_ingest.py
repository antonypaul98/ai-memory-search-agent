"""Synthetic consent and verifier-contract checks; no real identity claims."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.services.home_agent.verified_identity_ingest import (
    InstanceIdentityConsent, VerifiedInstanceIngestService, VerifiedInstanceProof,
)

NOW = datetime(2026, 10, 26, 6, tzinfo=timezone.utc)


class Verifier:
    def __init__(self, proof):
        self.proof = proof
        self.calls = []

    def verify(self, **kwargs):
        self.calls.append(kwargs)
        return self.proof


class Store:
    def __init__(self):
        self.writes = []

    def store_verified_instance_association(self, *, proof):
        self.writes.append(proof)
        return True


def fixture(proof=None):
    proof = proof if proof is not None else VerifiedInstanceProof(
        user_id="house-a", observation_id="obs-1", source_id="camera-1",
        instance_id="keys-1", identity_evidence_id="independent-verifier-1",
        identity_confidence=0.97,
    )
    verifier, store = Verifier(proof), Store()
    service = VerifiedInstanceIngestService(verifier=verifier, store=store)
    consent = InstanceIdentityConsent(
        user_id="house-a", source_id="camera-1",
        granted_at=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=1),
    )
    return service, verifier, store, consent


def ingest(service, consent, **overrides):
    kwargs = dict(user_id="house-a", observation_id="obs-1", source_id="camera-1",
                  consent=consent, now=NOW)
    kwargs.update(overrides)
    return service.ingest(**kwargs)


def test_trusted_proof_and_explicit_consent_are_required_for_write():
    service, verifier, store, consent = fixture()
    assert ingest(service, consent)
    assert len(store.writes) == 1
    assert verifier.calls == [dict(user_id="house-a", observation_id="obs-1", source_id="camera-1")]


@pytest.mark.parametrize("overrides", [
    {"user_id": "house-b"}, {"source_id": "camera-2"},
    {"now": NOW + timedelta(minutes=1)}, {"now": NOW - timedelta(minutes=2)},
])
def test_consent_is_tenant_source_and_time_bound(overrides):
    service, verifier, store, consent = fixture()
    with pytest.raises(PermissionError):
        ingest(service, consent, **overrides)
    assert verifier.calls == [] and store.writes == []


def test_no_verifier_result_fails_closed():
    service, verifier, store, consent = fixture()
    verifier.proof = None
    assert not ingest(service, consent)
    assert store.writes == []


@pytest.mark.parametrize("change", [
    {"user_id": "house-b"}, {"source_id": "camera-2"},
    {"observation_id": "obs-2"},
])
def test_mismatched_verifier_evidence_cannot_be_persisted(change):
    service, verifier, store, consent = fixture()
    verifier.proof = replace(verifier.proof, **change)
    with pytest.raises(PermissionError):
        ingest(service, consent)
    assert store.writes == []


def test_malformed_verifier_response_is_rejected():
    service, verifier, store, consent = fixture()
    verifier.proof = {"instance_id": "keys-1"}
    with pytest.raises(PermissionError):
        ingest(service, consent)
    assert store.writes == []


def test_low_confidence_does_not_persist():
    service, verifier, store, consent = fixture()
    verifier.proof = replace(verifier.proof, identity_confidence=0.89)
    assert not ingest(service, consent)
    assert store.writes == []


def test_observation_id_is_not_independent_identity_proof():
    service, verifier, store, consent = fixture()
    verifier.proof = replace(verifier.proof, identity_evidence_id="obs-1")
    with pytest.raises(ValueError):
        ingest(service, consent)
    assert store.writes == []


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, -0.1, 1.1])
def test_invalid_confidence_rejected_at_proof_construction(bad):
    with pytest.raises(ValueError):
        VerifiedInstanceProof("house-a", "obs-1", "camera-1", "keys-1", "proof-1", bad)


def test_naive_clock_or_invalid_consent_interval_rejected():
    with pytest.raises(ValueError):
        InstanceIdentityConsent("house-a", "camera-1", NOW, NOW)
    service, _, store, consent = fixture()
    with pytest.raises(ValueError):
        ingest(service, consent, now=NOW.replace(tzinfo=None))
    assert store.writes == []
