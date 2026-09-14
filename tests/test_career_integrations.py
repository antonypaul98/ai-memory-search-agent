from datetime import datetime, timezone

import pytest

from app.career.applications import ApplicationRegistry, ApplicationStatus, JobDescriptionSnapshot
from app.career.integrations import (
    InterviewEventRef,
    RecruiterMessageRef,
    attach_interview_event,
    attach_recruiter_message,
    build_quietcue_context,
)
from app.career.models import CareerFact, FactSensitivity, FactSource, MasterCareerProfile
from app.career.resume import tailor_resume


def _profile(tenant_id: str = "tenant-a") -> MasterCareerProfile:
    profile = MasterCareerProfile(tenant_id=tenant_id)
    profile.add_fact(
        CareerFact(
            key="skill.python",
            value="Python automation",
            source=FactSource.RESUME,
            evidence_ref="resume:python",
            confidence=0.98,
        )
    )
    profile.add_fact(
        CareerFact(
            key="project.qa",
            value="Built regression automation",
            source=FactSource.RESUME,
            sensitivity=FactSensitivity.PRIVATE,
            evidence_ref="resume:qa-project",
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


def _record(profile: MasterCareerProfile):
    resume = tailor_resume(
        profile,
        target_job_id="job-123",
        base_fact_keys=("skill.python", "project.qa"),
    )
    return ApplicationRegistry().create(
        tenant_id=profile.tenant_id,
        job=JobDescriptionSnapshot(
            job_fingerprint="job-123",
            title="QA Automation Engineer",
            company="Example Co",
            description="Build reliable test automation.",
            source_url="https://jobs.example.com/123",
            evidence_ref="job:123",
        ),
        resume=resume,
        application_id="app-1",
    )


def test_recruiter_message_adapter_preserves_provider_ids_and_evidence() -> None:
    record = _record(_profile())
    message = RecruiterMessageRef(
        provider="gmail",
        message_id="msg-1",
        thread_id="thread-1",
        subject="Interview availability",
        sender="recruiter@example.com",
        received_at=datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc),
        evidence_ref="gmail:msg-1",
    )

    attach_recruiter_message(record, message)

    assert record.recruiter_context == (
        "gmail:msg-1 | Interview availability | recruiter@example.com",
    )
    assert record.events[-1].evidence_ref == "gmail:msg-1"


def test_calendar_adapter_records_interview_and_advances_eligible_status() -> None:
    record = _record(_profile())
    record.transition_status(ApplicationStatus.SUBMITTED)
    event = InterviewEventRef(
        provider="google_calendar",
        event_id="event-1",
        title="Technical interview",
        starts_at=datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 9, 16, 15, 0, tzinfo=timezone.utc),
        evidence_ref="calendar:event-1",
        attendee_emails=("interviewer@example.com",),
    )

    attach_interview_event(record, event)

    assert record.status is ApplicationStatus.INTERVIEWING
    assert "google_calendar:event-1" in record.interview_history[-1]
    assert record.events[-1].evidence_ref == "calendar:event-1"


def test_quietcue_handoff_contains_exact_job_resume_and_verified_fact_provenance() -> None:
    profile = _profile()
    record = _record(profile)
    attach_recruiter_message(
        record,
        RecruiterMessageRef(
            provider="gmail",
            message_id="msg-1",
            thread_id=None,
            subject="Screening",
            sender="recruiter@example.com",
            received_at=datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc),
            evidence_ref="gmail:msg-1",
        ),
    )

    context = build_quietcue_context(record=record, profile=profile)

    assert context.application_id == "app-1"
    assert context.job_fingerprint == "job-123"
    assert context.job_description == "Build reliable test automation."
    assert context.resume_fact_keys == ("skill.python", "project.qa")
    assert [fact.key for fact in context.verified_candidate_facts] == [
        "skill.python",
        "project.qa",
    ]
    assert context.verified_candidate_facts[0].evidence_ref == "resume:python"
    assert context.recruiter_context[0].startswith("gmail:msg-1")


def test_quietcue_handoff_never_exposes_locked_facts() -> None:
    profile = _profile()
    record = _record(profile)
    # Simulate a legacy/malformed submitted snapshot containing a locked key.
    object.__setattr__(
        record.resume,
        "fact_keys",
        (*record.resume.fact_keys, "work.authorization"),
    )

    context = build_quietcue_context(record=record, profile=profile)

    assert "work.authorization" not in {
        fact.key for fact in context.verified_candidate_facts
    }


def test_quietcue_handoff_rejects_cross_tenant_profile() -> None:
    record = _record(_profile("tenant-a"))

    with pytest.raises(PermissionError, match="tenant"):
        build_quietcue_context(record=record, profile=_profile("tenant-b"))


def test_external_refs_require_timezone_aware_timestamps_and_valid_ranges() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        RecruiterMessageRef(
            provider="gmail",
            message_id="msg-1",
            thread_id=None,
            subject="Hello",
            sender="recruiter@example.com",
            received_at=datetime(2026, 9, 14, 12, 0),
            evidence_ref="gmail:msg-1",
        )

    start = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="end after"):
        InterviewEventRef(
            provider="google_calendar",
            event_id="event-1",
            title="Technical interview",
            starts_at=start,
            ends_at=start,
            evidence_ref="calendar:event-1",
        )
