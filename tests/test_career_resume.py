import pytest

from app.career import (
    CareerFact,
    FactSensitivity,
    FactSource,
    MasterCareerProfile,
    ResumeChangeKind,
    RoleVariant,
    tailor_resume,
)


def _profile() -> MasterCareerProfile:
    profile = MasterCareerProfile(tenant_id="tenant-a")
    profile.add_fact(
        CareerFact(
            key="experience.qa",
            value="Verified QA automation experience",
            source=FactSource.RESUME,
            evidence_ref="resume:experience:qa",
        )
    )
    profile.add_fact(
        CareerFact(
            key="skill.selenium",
            value="Selenium WebDriver",
            source=FactSource.RESUME,
            evidence_ref="resume:skills:selenium",
        )
    )
    profile.add_fact(
        CareerFact(
            key="skill.salesforce",
            value="Salesforce testing",
            source=FactSource.RESUME,
            evidence_ref="resume:skills:salesforce",
        )
    )
    return profile


def test_tailoring_only_uses_canonical_facts_and_tracks_exact_changes():
    profile = _profile()

    tailored = tailor_resume(
        profile,
        target_job_id="job-1",
        base_fact_keys=("experience.qa", "skill.selenium"),
        selected_fact_keys=("skill.salesforce", "experience.qa"),
    )

    assert tailored.fact_keys == ("skill.salesforce", "experience.qa")
    assert tailored.facts == (
        profile.resolve_fact("skill.salesforce"),
        profile.resolve_fact("experience.qa"),
    )
    assert [(change.kind, change.fact_key) for change in tailored.changes] == [
        (ResumeChangeKind.REMOVE, "skill.selenium"),
        (ResumeChangeKind.ADD, "skill.salesforce"),
        (ResumeChangeKind.REORDER, "experience.qa"),
    ]
    assert {change.evidence_ref for change in tailored.changes} == {
        "resume:skills:selenium",
        "resume:skills:salesforce",
        "resume:experience:qa",
    }


def test_tailoring_rejects_unknown_job_claim_instead_of_fabricating_it():
    profile = _profile()

    with pytest.raises(KeyError, match="unknown canonical career fact"):
        tailor_resume(
            profile,
            target_job_id="job-1",
            base_fact_keys=("experience.qa",),
            selected_fact_keys=("skill.copado",),
        )


def test_role_variant_can_drive_deterministic_resume_selection():
    profile = _profile()
    profile.add_role_variant(
        RoleVariant(
            name="salesforce-qa",
            fact_keys=("skill.salesforce", "experience.qa"),
        )
    )

    tailored = tailor_resume(
        profile,
        target_job_id="job-2",
        base_fact_keys=("experience.qa", "skill.selenium", "skill.salesforce"),
        role_variant="salesforce-qa",
    )

    assert tailored.role_variant == "salesforce-qa"
    assert tailored.fact_keys == ("skill.salesforce", "experience.qa")


def test_locked_application_fact_cannot_leak_into_resume():
    profile = _profile()
    profile.add_fact(
        CareerFact(
            key="work_authorization",
            value="verified-answer",
            source=FactSource.USER,
            sensitivity=FactSensitivity.LOCKED,
            evidence_ref="user-confirmation:work-auth",
        )
    )

    with pytest.raises(PermissionError, match="locked facts cannot be rendered"):
        tailor_resume(
            profile,
            target_job_id="job-3",
            base_fact_keys=("experience.qa",),
            selected_fact_keys=("experience.qa", "work_authorization"),
        )


def test_duplicate_selected_facts_are_rejected():
    profile = _profile()

    with pytest.raises(ValueError, match="selected resume fact keys must be unique"):
        tailor_resume(
            profile,
            target_job_id="job-4",
            base_fact_keys=("experience.qa",),
            selected_fact_keys=("experience.qa", "experience.qa"),
        )
