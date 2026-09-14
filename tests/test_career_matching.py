from __future__ import annotations

import pytest

from app.career.matching import JobRequirement, RequirementPriority, score_profile_fit
from app.career.models import CareerFact, FactSensitivity, FactSource, MasterCareerProfile


def _profile() -> MasterCareerProfile:
    profile = MasterCareerProfile(tenant_id="tenant-a")
    profile.add_fact(
        CareerFact(
            key="skills",
            value=["Selenium", "Salesforce", "Postman"],
            source=FactSource.RESUME,
            evidence_ref="resume:v3#skills",
        )
    )
    profile.add_fact(
        CareerFact(
            key="work_authorization",
            value="H-1B",
            source=FactSource.USER,
            sensitivity=FactSensitivity.LOCKED,
            evidence_ref="user-confirmation:work-auth",
        )
    )
    profile.add_fact(
        CareerFact(
            key="years_qa",
            value="4",
            source=FactSource.RESUME,
            evidence_ref="resume:v3#experience",
        )
    )
    return profile


def test_fit_score_weights_hard_requirements_more_than_preferred() -> None:
    result = score_profile_fit(
        _profile(),
        [
            JobRequirement("skills", RequirementPriority.HARD, ("selenium",)),
            JobRequirement("years_qa", RequirementPriority.HARD, ("4",)),
            JobRequirement("cloud", RequirementPriority.PREFERRED, ("aws",)),
        ],
    )

    assert result.score == 80.0
    assert result.hard_requirements_satisfied is True
    assert result.preferred_requirements_met == 0
    assert result.missing_fact_keys == ("cloud",)


def test_missing_hard_requirement_is_explicit_failure() -> None:
    result = score_profile_fit(
        _profile(),
        [JobRequirement("crt_experience", RequirementPriority.HARD, ("yes",))],
    )

    assert result.score == 0.0
    assert result.hard_requirements_satisfied is False
    assert result.hard_requirement_failures == ("crt_experience",)
    assert result.evidence[0].reason == "canonical fact is missing"


def test_private_or_locked_fact_value_is_redacted_from_evidence() -> None:
    result = score_profile_fit(
        _profile(),
        [JobRequirement("work_authorization", RequirementPriority.HARD, ("h-1b",))],
    )

    item = result.evidence[0]
    assert item.matched is True
    assert item.fact_key == "work_authorization"
    assert item.evidence_ref == "user-confirmation:work-auth"
    assert item.fact_value is None


def test_public_fact_keeps_explainable_value_and_provenance() -> None:
    result = score_profile_fit(
        _profile(),
        [JobRequirement("skills", RequirementPriority.PREFERRED, ("salesforce",))],
    )

    item = result.evidence[0]
    assert item.matched is True
    assert item.fact_value == ["Selenium", "Salesforce", "Postman"]
    assert item.evidence_ref == "resume:v3#skills"


def test_nonmatching_canonical_fact_is_not_treated_as_missing() -> None:
    result = score_profile_fit(
        _profile(),
        [JobRequirement("years_qa", RequirementPriority.HARD, ("5",))],
    )

    assert result.hard_requirement_failures == ("years_qa",)
    assert result.missing_fact_keys == ()
    assert result.evidence[0].reason == "canonical fact does not satisfy accepted values"


def test_empty_requirement_set_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one job requirement"):
        score_profile_fit(_profile(), [])
