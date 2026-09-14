from datetime import datetime, timezone

import pytest

from app.career.applications import ApplicationRegistry, JobDescriptionSnapshot
from app.career.models import CareerFact, FactSensitivity, FactSource, MasterCareerProfile
from app.career.post_interview import (
    InterviewLearning,
    PostInterviewMemory,
    build_next_round_preparation,
    record_post_interview_learnings,
)
from app.career.resume import tailor_resume


def _profile(tenant_id: str = "tenant-a") -> MasterCareerProfile:
    profile = MasterCareerProfile(tenant_id=tenant_id)
    profile.add_fact(
        CareerFact(
            key="skill.python",
            value="Python automation",
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


def _record(profile: MasterCareerProfile):
    resume = tailor_resume(
        profile,
        target_job_id="job-123",
        base_fact_keys=("skill.python",),
    )
    return ApplicationRegistry().create(
        tenant_id=profile.tenant_id,
        job=JobDescriptionSnapshot(
            job_fingerprint="job-123",
            title="QA Automation Engineer",
            company="Example Co",
            description="Build reliable test automation.",
            evidence_ref="job:123",
        ),
        resume=resume,
        application_id="app-1",
    )


def test_post_interview_learning_is_evidence_bearing_and_added_to_history() -> None:
    profile = _profile()
    record = _record(profile)
    memory = PostInterviewMemory()
    learning = InterviewLearning(
        topic="api-testing",
        detail="Interviewer focused on REST validation and downstream reconciliation.",
        evidence_ref="interview:round-1:notes",
        occurred_at=datetime(2026, 9, 14, 15, 0, tzinfo=timezone.utc),
    )

    stored = record_post_interview_learnings(
        memory=memory,
        record=record,
        learnings=(learning,),
    )

    assert stored == (learning,)
    assert memory.list_for_application(
        tenant_id="tenant-a", application_id="app-1"
    ) == (learning,)
    assert record.events[-1].evidence_ref == "interview:round-1:notes"
    assert "api-testing" in record.interview_history[-1]


def test_next_round_preparation_deduplicates_topics_and_uses_only_verified_resume_facts() -> None:
    profile = _profile()
    record = _record(profile)
    memory = PostInterviewMemory()
    when = datetime(2026, 9, 14, 15, 0, tzinfo=timezone.utc)
    record_post_interview_learnings(
        memory=memory,
        record=record,
        learnings=(
            InterviewLearning("api-testing", "REST questions", occurred_at=when),
            InterviewLearning("api-testing", "More REST questions", occurred_at=when),
            InterviewLearning("salesforce", "SOQL validation", occurred_at=when),
        ),
    )

    prep = build_next_round_preparation(record=record, profile=profile, memory=memory)

    assert prep.focus_topics == ("api-testing", "salesforce")
    assert prep.verified_fact_keys == ("skill.python",)
    assert prep.company == "Example Co"
    assert prep.job_title == "QA Automation Engineer"


def test_next_round_preparation_excludes_locked_facts_even_if_legacy_snapshot_contains_one() -> None:
    profile = _profile()
    record = _record(profile)
    object.__setattr__(record.resume, "fact_keys", ("skill.python", "work.authorization"))

    prep = build_next_round_preparation(
        record=record,
        profile=profile,
        memory=PostInterviewMemory(),
    )

    assert prep.verified_fact_keys == ("skill.python",)


def test_post_interview_memory_is_tenant_scoped() -> None:
    memory = PostInterviewMemory()
    learning = InterviewLearning("system-design", "Asked about scale")
    memory.add(tenant_id="tenant-a", application_id="app-1", learning=learning)

    assert memory.list_for_application(tenant_id="tenant-b", application_id="app-1") == ()


def test_next_round_preparation_rejects_cross_tenant_profile() -> None:
    record = _record(_profile("tenant-a"))

    with pytest.raises(PermissionError, match="tenant"):
        build_next_round_preparation(
            record=record,
            profile=_profile("tenant-b"),
            memory=PostInterviewMemory(),
        )


def test_interview_learning_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        InterviewLearning(
            topic="python",
            detail="Asked about fixtures",
            occurred_at=datetime(2026, 9, 14, 15, 0),
        )
