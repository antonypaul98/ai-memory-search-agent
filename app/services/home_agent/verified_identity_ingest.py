"""Internal, opt-in boundary for independently verified object-instance evidence.

This module does not recognize objects, mint proofs, or expose a public API.
An explicitly configured trusted verifier must inspect retained sighting
provenance and establish physical-instance identity independently of class
labels. An authenticated server component must issue the consent grant.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Protocol

MIN_IDENTITY_CONFIDENCE = 0.9


def _required_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")


def _aware(name: str, value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class InstanceIdentityConsent:
    """Server-issued, tenant/source-scoped consent for identity associations."""

    user_id: str
    source_id: str
    granted_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _required_text("user_id", self.user_id)
        _required_text("source_id", self.source_id)
        _aware("granted_at", self.granted_at)
        _aware("expires_at", self.expires_at)
        if self.expires_at <= self.granted_at:
            raise ValueError("expires_at must follow granted_at")

    def allows(self, *, user_id: str, source_id: str, now: datetime) -> bool:
        _aware("now", now)
        return (self.user_id == user_id and self.source_id == source_id
                and self.granted_at <= now < self.expires_at)


@dataclass(frozen=True, slots=True)
class VerifiedInstanceProof:
    """A verifier-produced association, not a client-submitted assertion."""

    user_id: str
    observation_id: str
    source_id: str
    instance_id: str
    identity_evidence_id: str
    identity_confidence: float

    def __post_init__(self) -> None:
        for name in ("user_id", "observation_id", "source_id", "instance_id", "identity_evidence_id"):
            _required_text(name, getattr(self, name))
        if (isinstance(self.identity_confidence, bool)
                or not isinstance(self.identity_confidence, (int, float))
                or not isfinite(self.identity_confidence)
                or not 0 <= self.identity_confidence <= 1):
            raise ValueError("identity_confidence must be finite and between 0 and 1")


class TrustedInstanceVerifier(Protocol):
    def verify(self, *, user_id: str, observation_id: str, source_id: str) -> VerifiedInstanceProof | None: ...


class VerifiedAssociationWriter(Protocol):
    def store_verified_instance_association(self, *, proof: VerifiedInstanceProof) -> bool: ...


class VerifiedInstanceIngestService:
    """Accept identity evidence only from a trusted verifier under explicit consent.

    This is not wired to a camera, public endpoint or database writer. Those
    components must independently enforce tenant ownership, observation
    provenance, proof uniqueness, revocation and transactional persistence.
    """

    def __init__(self, *, verifier: TrustedInstanceVerifier, store: VerifiedAssociationWriter):
        self._verifier = verifier
        self._store = store

    def ingest(
        self, *, user_id: str, observation_id: str, source_id: str,
        consent: InstanceIdentityConsent, now: datetime | None = None,
    ) -> bool:
        for name, value in (("user_id", user_id), ("observation_id", observation_id),
                            ("source_id", source_id)):
            _required_text(name, value)
        resolved_now = datetime.now(timezone.utc) if now is None else now
        _aware("now", resolved_now)
        if not isinstance(consent, InstanceIdentityConsent) or not consent.allows(
            user_id=user_id, source_id=source_id, now=resolved_now,
        ):
            raise PermissionError("identity association consent is missing, mismatched, or expired")
        proof = self._verifier.verify(
            user_id=user_id, observation_id=observation_id, source_id=source_id,
        )
        if proof is None:
            return False
        if (not isinstance(proof, VerifiedInstanceProof)
                or proof.user_id != user_id or proof.observation_id != observation_id
                or proof.source_id != source_id):
            raise PermissionError("identity verifier returned mismatched evidence")
        if proof.identity_evidence_id == observation_id:
            raise ValueError("identity proof must be independent of the sighting ID")
        if proof.identity_confidence < MIN_IDENTITY_CONFIDENCE:
            return False
        return self._store.store_verified_instance_association(proof=proof)
