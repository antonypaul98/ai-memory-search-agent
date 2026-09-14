from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from .applications import ApplicationRecord
from .models import FactSensitivity, MasterCareerProfile


@dataclass(frozen=True, slots=True)
class InterviewLearning:
    topic: str
    detail: str
    evidence_ref: str | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.topic.strip():
            raise ValueError("interview learning topic must not be empty")
        if not self.detail.strip():
            raise ValueError("interview learning detail must not be empty")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("interview learning timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True)
class NextRoundPreparation:
    application_id: str
    tenant_id: str
    company: str
    job_title: str
    focus_topics: tuple[str, ...]
    verified_fact_keys: tuple[str, ...]
    recruiter_context: tuple[str, ...]
    interview_history: tuple[str, ...]


@dataclass(slots=True)
class PostInterviewMemory:
    """Tenant-scoped post-interview memory for one application.

    Interview learnings are retained as evidence-bearing observations. They do not
    silently mutate the canonical MasterCareerProfile; promotion into canonical
    facts must happen through the normal explicit profile update path.
    """

    _items_by_tenant: dict[str, dict[str, list[InterviewLearning]]] = field(default_factory=dict)

    def add(
        self,
        *,
        tenant_id: str,
        application_id: str,
        learning: InterviewLearning,
    ) -> None:
        if not tenant_id.strip():
            raise ValueError("tenant_id must not be empty")
        if not application_id.strip():
            raise ValueError("application_id must not be empty")
        applications = self._items_by_tenant.setdefault(tenant_id, {})
        applications.setdefault(application_id, []).append(learning)

    def list_for_application(
        self, *, tenant_id: str, application_id: str
    ) -> tuple[InterviewLearning, ...]:
        if not tenant_id.strip():
            raise ValueError("tenant_id must not be empty")
        if not application_id.strip():
            raise ValueError("application_id must not be empty")
        return tuple(self._items_by_tenant.get(tenant_id, {}).get(application_id, ()))


def record_post_interview_learnings(
    *,
    memory: PostInterviewMemory,
    record: ApplicationRecord,
    learnings: Iterable[InterviewLearning],
) -> tuple[InterviewLearning, ...]:
    stored: list[InterviewLearning] = []
    for learning in learnings:
        memory.add(
            tenant_id=record.tenant_id,
            application_id=record.application_id,
            learning=learning,
        )
        record.add_interview_history(
            f"post-interview:{learning.topic} | {learning.detail}",
            occurred_at=learning.occurred_at,
            evidence_ref=learning.evidence_ref,
        )
        stored.append(learning)
    return tuple(stored)


def build_next_round_preparation(
    *,
    record: ApplicationRecord,
    profile: MasterCareerProfile,
    memory: PostInterviewMemory,
) -> NextRoundPreparation:
    if profile.tenant_id != record.tenant_id:
        raise PermissionError("career profile tenant does not match application tenant")

    learnings = memory.list_for_application(
        tenant_id=record.tenant_id,
        application_id=record.application_id,
    )

    topics: list[str] = []
    seen_topics: set[str] = set()
    for learning in learnings:
        normalized = learning.topic.strip()
        if normalized not in seen_topics:
            seen_topics.add(normalized)
            topics.append(normalized)

    verified_fact_keys: list[str] = []
    for key in record.resume.fact_keys:
        fact = profile.resolve_fact(key)
        if fact.sensitivity is FactSensitivity.LOCKED:
            continue
        verified_fact_keys.append(key)

    return NextRoundPreparation(
        application_id=record.application_id,
        tenant_id=record.tenant_id,
        company=record.job.company,
        job_title=record.job.title,
        focus_topics=tuple(topics),
        verified_fact_keys=tuple(verified_fact_keys),
        recruiter_context=record.recruiter_context,
        interview_history=record.interview_history,
    )
