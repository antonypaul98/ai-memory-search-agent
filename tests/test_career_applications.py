from datetime import datetime, timezone

import pytest

from app.career.application_answers import (
    ApplicationQuestion,
    generate_application_answer,
)
from app.career.applications import (
    ApplicationEventKind,
    ApplicationRegistry,
    ApplicationStatus,
    JobDescriptionSnapshot,
)
from app.career.models import (
    CareerFact,
    FactSensitivity,
    FactSource,
    MasterCareerProfile,
)
from app.career.resume import tailor_resume


def _profile(tenant_id: str) -> MasterCareerProfile:
    profile = MasterCareerProfile(tenant_id=tenant_id)
    profile.add_fact(
        CareerFact(
            key="skill.python",
            value="Python",
            source=FactSource.RESUME,
            evidence_ref="resume:python",
        )
    )
    profile.add_fact(
        CareerFact(
            key="work.authorization",
            value="authorized",
            source=FactSource.USER,
            sensitivity=FactSensitivity.LOCKED,
            evidence_ref="user:work-auth",
        )
    )
    return profile


def _job() -> JobDescriptionSnapshot:
    return JobDescriptionSnapshot(
        job_fingerprint="job-123",
        title="QA Automation Engineer",
        company="Example Co",
        description="Build and maintain automation.",
        source_url="https://jobs.example.com/123",
        evidence_ref="job:123",
    )


def test_application_record_snapshots_job_resume_answers_and_history() -> None:
    profile = _profile("tenant-a")
    resume = tailor_resume(
        profile,
        target_job_id="job-123",
        base_fact_keys=("skill.python",),
    )
    answer = generate_application_answer(
        profile,
        ApplicationQuestion(
            question_id="q-work-auth",
            prompt="Are you authorized to work?",
            fact_key="work.authorization",
            require_locked_fact=True,
        ),
        confirmed_locked_keys=("work.authorization",),
    )
    created_at = datetime(2026, 9, 14, 5, 0, tzinfo=timezone.utc)
    registry = ApplicationRegistry()

    record = registry.create(
        tenant_id="tenant-a",
        job=_job(),
        resume=resume,
        answers=(answer,),
        source="linkedin",
        application_id="app-1",
        created_at=created_at,
    )

    assert record.job.description == "Build and maintain automation."
    assert record.resume.fact_keys == ("skill.python",)
    assert record.answers[0].fact_key == "work.authorization"
    assert record.answers[0].evidence_ref == "user:work-auth"
    assert record.events[0].kind is ApplicationEventKind.CREATED

    record.transition_status(
        ApplicationStatus.SUBMITTED,
        occurred_at=datetime(2026, 9, 14, 5, 5, tzinfo=timezone.utc),
        evidence_ref="ats:confirmation",
    )
    record.add_recruiter_context(
        "Recruiter requested a screening call",
        occurred_at=datetime(2026, 9, 14, 6, 0, tzinfo=timezone.utc),
        evidence_ref="gmail:message-1",
    )
    record.add_interview_history(
        "Technical screen covered Selenium and API testing",
        occurred_at=datetime(2026, 9, 15, 14, 0, tzinfo=timezone.utc),
        evidence_ref="interview:screen-1",
    )

    assert record.status is ApplicationStatus.SUBMITTED
    assert record.applied_at == datetime(2026, 9, 14, 5, 5, tzinfo=timezone.utc)
    assert record.recruiter_context == ("Recruiter requested a screening call",)
    assert record.interview_history == (
        "Technical screen covered Selenium and API testing",
    )
    assert [event.kind for event in record.events] == [
        ApplicationEventKind.CREATED,
        ApplicationEventKind.STATUS_CHANGED,
        ApplicationEventKind.RECRUITER_NOTE,
        ApplicationEventKind.INTERVIEW_NOTE,
    ]


def test_application_registry_enforces_tenant_isolation() -> None:
    profile = _profile("tenant-a")
    resume = tailor_resume(
        profile,
        target_job_id="job-123",
        base_fact_keys=("skill.python",),
    )
    registry = ApplicationRegistry()
    registry.create(
        tenant_id="tenant-a",
        job=_job(),
        resume=resume,
        application_id="app-1",
    )

    with pytest.raises(KeyError, match="unknown tenant-scoped application record"):
        registry.get("tenant-b", "app-1")


def test_application_registry_rejects_cross_tenant_resume() -> None:
    profile = _profile("tenant-a")
    resume = tailor_resume(
        profile,
        target_job_id="job-123",
        base_fact_keys=("skill.python",),
    )

    with pytest.raises(PermissionError, match="resume tenant"):
        ApplicationRegistry().create(
            tenant_id="tenant-b",
            job=_job(),
            resume=resume,
        )


def test_application_registry_rejects_wrong_job_resume() -> None:
    profile = _profile("tenant-a")
    resume = tailor_resume(
        profile,
        target_job_id="different-job",
        base_fact_keys=("skill.python",),
    )

    with pytest.raises(ValueError, match="resume target"):
        ApplicationRegistry().create(
            tenant_id="tenant-a",
            job=_job(),
            resume=resume,
        )


def test_application_timestamps_must_be_timezone_aware() -> None:
    profile = _profile("tenant-a")
    resume = tailor_resume(
        profile,
        target_job_id="job-123",
        base_fact_keys=("skill.python",),
    )
    registry = ApplicationRegistry()

    with pytest.raises(ValueError, match="timezone-aware"):
        registry.create(
            tenant_id="tenant-a",
            job=_job(),
            resume=resume,
            created_at=datetime(2026, 9, 14, 5, 0),
        )
