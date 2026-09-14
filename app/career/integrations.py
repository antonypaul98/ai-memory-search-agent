from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from .applications import ApplicationRecord, ApplicationStatus
from .models import FactSensitivity, MasterCareerProfile


@dataclass(frozen=True, slots=True)
class RecruiterMessageRef:
    """Provider-neutral pointer to an authorized recruiter message.

    The Career domain stores stable identifiers and evidence references only; it
    does not require Gmail credentials or raw connector tokens.
    """

    provider: str
    message_id: str
    thread_id: str | None
    subject: str
    sender: str
    received_at: datetime
    evidence_ref: str

    def __post_init__(self) -> None:
        for field_name in ("provider", "message_id", "subject", "sender", "evidence_ref"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.received_at.tzinfo is None or self.received_at.utcoffset() is None:
            raise ValueError("received_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class InterviewEventRef:
    """Provider-neutral pointer to an authorized calendar interview event."""

    provider: str
    event_id: str
    title: str
    starts_at: datetime
    ends_at: datetime
    evidence_ref: str
    attendee_emails: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("provider", "event_id", "title", "evidence_ref"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")
        for value, name in ((self.starts_at, "starts_at"), (self.ends_at, "ends_at")):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.ends_at <= self.starts_at:
            raise ValueError("interview event must end after it starts")


class RecruiterMessageSource(Protocol):
    """Read-only boundary implemented by an authorized mail connector."""

    def get_message(self, message_id: str) -> RecruiterMessageRef: ...


class InterviewCalendarSource(Protocol):
    """Read-only boundary implemented by an authorized calendar connector."""

    def get_event(self, event_id: str) -> InterviewEventRef: ...


def attach_recruiter_message(record: ApplicationRecord, message: RecruiterMessageRef) -> None:
    detail = f"{message.provider}:{message.message_id} | {message.subject} | {message.sender}"
    record.add_recruiter_context(
        detail,
        occurred_at=message.received_at,
        evidence_ref=message.evidence_ref,
    )


def attach_interview_event(record: ApplicationRecord, event: InterviewEventRef) -> None:
    detail = (
        f"{event.provider}:{event.event_id} | {event.title} | "
        f"{event.starts_at.isoformat()}->{event.ends_at.isoformat()}"
    )
    record.add_interview_history(
        detail,
        occurred_at=event.starts_at,
        evidence_ref=event.evidence_ref,
    )
    if record.status in {
        ApplicationStatus.DRAFT,
        ApplicationStatus.READY,
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.SCREENING,
    }:
        record.transition_status(
            ApplicationStatus.INTERVIEWING,
            occurred_at=event.starts_at,
            evidence_ref=event.evidence_ref,
        )


@dataclass(frozen=True, slots=True)
class QuietCueCareerFact:
    key: str
    value: Any
    sensitivity: FactSensitivity
    confidence: float
    evidence_ref: str | None


@dataclass(frozen=True, slots=True)
class QuietCueApplicationContext:
    """Exact, privacy-aware application snapshot handed to QuietCue."""

    tenant_id: str
    application_id: str
    job_fingerprint: str
    job_title: str
    company: str
    job_description: str
    job_source_url: str | None
    resume_fact_keys: tuple[str, ...]
    role_variant: str | None
    verified_candidate_facts: tuple[QuietCueCareerFact, ...]
    recruiter_context: tuple[str, ...]
    interview_history: tuple[str, ...]


def build_quietcue_context(
    *,
    record: ApplicationRecord,
    profile: MasterCareerProfile,
) -> QuietCueApplicationContext:
    """Build a deterministic handoff without leaking locked application facts.

    Only canonical facts that were present in the submitted resume are exposed.
    LOCKED facts (work authorization, sponsorship, citizenship, EEO, etc.) are
    intentionally withheld from live interview context even if a caller managed
    to reference one in a resume snapshot.
    """

    if profile.tenant_id != record.tenant_id:
        raise PermissionError("career profile tenant does not match application tenant")

    facts: list[QuietCueCareerFact] = []
    for key in record.resume.fact_keys:
        fact = profile.resolve_fact(key)
        if fact.sensitivity is FactSensitivity.LOCKED:
            continue
        facts.append(
            QuietCueCareerFact(
                key=fact.key,
                value=fact.value,
                sensitivity=fact.sensitivity,
                confidence=fact.confidence,
                evidence_ref=fact.evidence_ref,
            )
        )

    return QuietCueApplicationContext(
        tenant_id=record.tenant_id,
        application_id=record.application_id,
        job_fingerprint=record.job.job_fingerprint,
        job_title=record.job.title,
        company=record.job.company,
        job_description=record.job.description,
        job_source_url=record.job.source_url,
        resume_fact_keys=record.resume.fact_keys,
        role_variant=record.resume.role_variant,
        verified_candidate_facts=tuple(facts),
        recruiter_context=record.recruiter_context,
        interview_history=record.interview_history,
    )
