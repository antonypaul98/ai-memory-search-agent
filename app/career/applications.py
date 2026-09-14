from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable
from uuid import uuid4

from .application_answers import GeneratedApplicationAnswer
from .resume import TailoredResume


class ApplicationStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    SUBMITTED = "submitted"
    SCREENING = "screening"
    INTERVIEWING = "interviewing"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class ApplicationEventKind(str, Enum):
    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    RECRUITER_NOTE = "recruiter_note"
    INTERVIEW_NOTE = "interview_note"


@dataclass(frozen=True, slots=True)
class JobDescriptionSnapshot:
    job_fingerprint: str
    title: str
    company: str
    description: str
    source_url: str | None = None
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("job_fingerprint", "title", "company", "description"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")


@dataclass(frozen=True, slots=True)
class SubmittedResumeSnapshot:
    target_job_id: str
    fact_keys: tuple[str, ...]
    role_variant: str | None
    change_count: int

    @classmethod
    def from_tailored_resume(cls, resume: TailoredResume) -> "SubmittedResumeSnapshot":
        return cls(
            target_job_id=resume.target_job_id,
            fact_keys=resume.fact_keys,
            role_variant=resume.role_variant,
            change_count=len(resume.changes),
        )


@dataclass(frozen=True, slots=True)
class ApplicationAnswerSnapshot:
    question_id: str
    fact_key: str
    status: str
    text: str | None
    evidence_ref: str | None

    @classmethod
    def from_generated_answer(
        cls, answer: GeneratedApplicationAnswer
    ) -> "ApplicationAnswerSnapshot":
        return cls(
            question_id=answer.question_id,
            fact_key=answer.fact_key,
            status=answer.status.value,
            text=answer.text,
            evidence_ref=answer.evidence_ref,
        )


@dataclass(frozen=True, slots=True)
class ApplicationEvent:
    kind: ApplicationEventKind
    occurred_at: datetime
    detail: str
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("application event timestamp must be timezone-aware")
        if not self.detail.strip():
            raise ValueError("application event detail must not be empty")


@dataclass(slots=True)
class ApplicationRecord:
    application_id: str
    tenant_id: str
    job: JobDescriptionSnapshot
    resume: SubmittedResumeSnapshot
    answers: tuple[ApplicationAnswerSnapshot, ...] = ()
    status: ApplicationStatus = ApplicationStatus.DRAFT
    source: str | None = None
    applied_at: datetime | None = None
    recruiter_context: tuple[str, ...] = ()
    interview_history: tuple[str, ...] = ()
    events: list[ApplicationEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.application_id.strip():
            raise ValueError("application_id must not be empty")
        if not self.tenant_id.strip():
            raise ValueError("tenant_id must not be empty")
        if self.resume.target_job_id != self.job.job_fingerprint:
            raise ValueError("submitted resume must target the application job fingerprint")
        if self.applied_at is not None and (
            self.applied_at.tzinfo is None or self.applied_at.utcoffset() is None
        ):
            raise ValueError("applied_at must be timezone-aware")

    def transition_status(
        self,
        status: ApplicationStatus,
        *,
        occurred_at: datetime | None = None,
        evidence_ref: str | None = None,
    ) -> None:
        if status is self.status:
            return
        if status is ApplicationStatus.SUBMITTED and self.applied_at is None:
            self.applied_at = occurred_at or datetime.now(timezone.utc)
        previous = self.status
        self.status = status
        self.events.append(
            ApplicationEvent(
                kind=ApplicationEventKind.STATUS_CHANGED,
                occurred_at=occurred_at or datetime.now(timezone.utc),
                detail=f"{previous.value}->{status.value}",
                evidence_ref=evidence_ref,
            )
        )

    def add_recruiter_context(
        self,
        detail: str,
        *,
        occurred_at: datetime | None = None,
        evidence_ref: str | None = None,
    ) -> None:
        if not detail.strip():
            raise ValueError("recruiter context must not be empty")
        self.recruiter_context = (*self.recruiter_context, detail)
        self.events.append(
            ApplicationEvent(
                kind=ApplicationEventKind.RECRUITER_NOTE,
                occurred_at=occurred_at or datetime.now(timezone.utc),
                detail=detail,
                evidence_ref=evidence_ref,
            )
        )

    def add_interview_history(
        self,
        detail: str,
        *,
        occurred_at: datetime | None = None,
        evidence_ref: str | None = None,
    ) -> None:
        if not detail.strip():
            raise ValueError("interview history must not be empty")
        self.interview_history = (*self.interview_history, detail)
        self.events.append(
            ApplicationEvent(
                kind=ApplicationEventKind.INTERVIEW_NOTE,
                occurred_at=occurred_at or datetime.now(timezone.utc),
                detail=detail,
                evidence_ref=evidence_ref,
            )
        )


@dataclass(slots=True)
class ApplicationRegistry:
    """Tenant-scoped application-memory boundary.

    The registry stores immutable JD/resume/answer snapshots plus an append-only
    event trail for status, recruiter, and interview history. Persistence adapters
    can mirror this contract without changing the domain model.
    """

    _records_by_tenant: dict[str, dict[str, ApplicationRecord]] = field(default_factory=dict)

    def create(
        self,
        *,
        tenant_id: str,
        job: JobDescriptionSnapshot,
        resume: TailoredResume,
        answers: Iterable[GeneratedApplicationAnswer] = (),
        source: str | None = None,
        application_id: str | None = None,
        created_at: datetime | None = None,
    ) -> ApplicationRecord:
        if not tenant_id.strip():
            raise ValueError("tenant_id must not be empty")
        if resume.tenant_id != tenant_id:
            raise PermissionError("resume tenant does not match application tenant")
        if resume.target_job_id != job.job_fingerprint:
            raise ValueError("resume target does not match job fingerprint")

        record_id = application_id or str(uuid4())
        tenant_records = self._records_by_tenant.setdefault(tenant_id, {})
        if record_id in tenant_records:
            raise ValueError(f"application record already exists: {record_id}")

        answer_snapshots = tuple(
            ApplicationAnswerSnapshot.from_generated_answer(answer) for answer in answers
        )
        record = ApplicationRecord(
            application_id=record_id,
            tenant_id=tenant_id,
            job=job,
            resume=SubmittedResumeSnapshot.from_tailored_resume(resume),
            answers=answer_snapshots,
            source=source,
        )
        record.events.append(
            ApplicationEvent(
                kind=ApplicationEventKind.CREATED,
                occurred_at=created_at or datetime.now(timezone.utc),
                detail="application record created",
            )
        )
        tenant_records[record_id] = record
        return record

    def get(self, tenant_id: str, application_id: str) -> ApplicationRecord:
        if not tenant_id.strip():
            raise ValueError("tenant_id must not be empty")
        try:
            return self._records_by_tenant[tenant_id][application_id]
        except KeyError as exc:
            raise KeyError("unknown tenant-scoped application record") from exc

    def list_for_tenant(self, tenant_id: str) -> tuple[ApplicationRecord, ...]:
        if not tenant_id.strip():
            raise ValueError("tenant_id must not be empty")
        records = self._records_by_tenant.get(tenant_id, {})
        return tuple(records[key] for key in sorted(records))
