import pytest

from app.career import (
    CareerFact,
    FactSensitivity,
    FactSource,
    MasterCareerProfile,
    RoleVariant,
)


def test_locked_fact_requires_non_system_evidence():
    with pytest.raises(ValueError, match="locked career facts"):
        CareerFact(
            key="work_authorization",
            value="verified-value",
            source=FactSource.SYSTEM,
            sensitivity=FactSensitivity.LOCKED,
        )


def test_locked_fact_cannot_be_changed_implicitly():
    profile = MasterCareerProfile(tenant_id="tenant-a")
    profile.add_fact(
        CareerFact(
            key="sponsorship_required",
            value=True,
            source=FactSource.USER,
            sensitivity=FactSensitivity.LOCKED,
            evidence_ref="user-confirmation:1",
        )
    )

    with pytest.raises(PermissionError, match="cannot be changed implicitly"):
        profile.add_fact(
            CareerFact(
                key="sponsorship_required",
                value=False,
                source=FactSource.IMPORT,
                sensitivity=FactSensitivity.LOCKED,
                evidence_ref="import:1",
            ),
            replace=True,
        )


def test_role_variant_only_references_canonical_facts():
    profile = MasterCareerProfile(tenant_id="tenant-a")
    profile.add_fact(
        CareerFact(
            key="skill.selenium",
            value="Selenium WebDriver",
            source=FactSource.RESUME,
            evidence_ref="resume:skills",
        )
    )

    with pytest.raises(ValueError, match="unknown facts"):
        profile.add_role_variant(
            RoleVariant(
                name="salesforce-qa",
                fact_keys=("skill.selenium", "skill.copado"),
            )
        )


def test_role_variant_resolves_same_canonical_fact_objects():
    profile = MasterCareerProfile(tenant_id="tenant-a")
    selenium = CareerFact(
        key="skill.selenium",
        value="Selenium WebDriver",
        source=FactSource.RESUME,
        evidence_ref="resume:skills",
    )
    qa = CareerFact(
        key="experience.qa_automation",
        value="verified experience",
        source=FactSource.RESUME,
        evidence_ref="resume:experience:1",
    )
    profile.add_fact(selenium)
    profile.add_fact(qa)
    profile.add_role_variant(
        RoleVariant(
            name="qa-automation",
            fact_keys=(selenium.key, qa.key),
            summary="QA automation emphasis",
        )
    )

    assert profile.resolve_role_variant("qa-automation") == (selenium, qa)


def test_protected_answer_requires_locked_fact():
    profile = MasterCareerProfile(tenant_id="tenant-a")
    profile.add_fact(
        CareerFact(
            key="preferred_title",
            value="QA Automation Engineer",
            source=FactSource.USER,
        )
    )

    with pytest.raises(PermissionError, match="not locked"):
        profile.require_locked_facts(["preferred_title"])
