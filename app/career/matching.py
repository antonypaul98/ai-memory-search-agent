from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from .models import CareerFact, FactSensitivity, MasterCareerProfile


class RequirementPriority(str, Enum):
    HARD = "hard"
    PREFERRED = "preferred"


@dataclass(frozen=True, slots=True)
class JobRequirement:
    key: str
    priority: RequirementPriority
    accepted_values: tuple[str, ...] = ()
    label: str | None = None

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("requirement key must not be empty")
        if self.accepted_values and any(not value.strip() for value in self.accepted_values):
            raise ValueError("accepted requirement values must not be empty")


@dataclass(frozen=True, slots=True)
class RequirementEvidence:
    requirement_key: str
    priority: RequirementPriority
    matched: bool
    fact_key: str | None
    evidence_ref: str | None
    reason: str
    fact_value: Any | None = None


@dataclass(frozen=True, slots=True)
class FitScore:
    score: float
    hard_requirements_met: int
    hard_requirements_total: int
    preferred_requirements_met: int
    preferred_requirements_total: int
    hard_requirement_failures: tuple[str, ...]
    missing_fact_keys: tuple[str, ...]
    evidence: tuple[RequirementEvidence, ...]

    @property
    def hard_requirements_satisfied(self) -> bool:
        return self.hard_requirements_met == self.hard_requirements_total


def _fact_matches(fact: CareerFact, accepted_values: tuple[str, ...]) -> bool:
    if not accepted_values:
        return True

    value = fact.value
    if isinstance(value, str):
        candidates = {value.strip().casefold()}
    elif isinstance(value, (list, tuple, set, frozenset)):
        candidates = {str(item).strip().casefold() for item in value}
    else:
        candidates = {str(value).strip().casefold()}

    expected = {item.strip().casefold() for item in accepted_values}
    return bool(candidates & expected)


def _safe_fact_value(fact: CareerFact) -> Any | None:
    if fact.sensitivity is not FactSensitivity.PUBLIC:
        return None
    return fact.value


def score_profile_fit(
    profile: MasterCareerProfile,
    requirements: Iterable[JobRequirement],
) -> FitScore:
    requirements_tuple = tuple(requirements)
    if not requirements_tuple:
        raise ValueError("at least one job requirement is required")

    evidence: list[RequirementEvidence] = []
    missing_keys: set[str] = set()
    hard_failures: list[str] = []
    hard_total = hard_met = preferred_total = preferred_met = 0
    earned_weight = total_weight = 0.0

    for requirement in requirements_tuple:
        weight = 2.0 if requirement.priority is RequirementPriority.HARD else 1.0
        total_weight += weight
        if requirement.priority is RequirementPriority.HARD:
            hard_total += 1
        else:
            preferred_total += 1

        fact = profile.facts.get(requirement.key)
        if fact is None:
            missing_keys.add(requirement.key)
            reason = "canonical fact is missing"
            if requirement.priority is RequirementPriority.HARD:
                hard_failures.append(requirement.key)
            evidence.append(
                RequirementEvidence(
                    requirement_key=requirement.key,
                    priority=requirement.priority,
                    matched=False,
                    fact_key=None,
                    evidence_ref=None,
                    reason=reason,
                )
            )
            continue

        matched = _fact_matches(fact, requirement.accepted_values)
        if matched:
            earned_weight += weight
            if requirement.priority is RequirementPriority.HARD:
                hard_met += 1
            else:
                preferred_met += 1
            reason = "canonical fact satisfies requirement"
        else:
            reason = "canonical fact does not satisfy accepted values"
            if requirement.priority is RequirementPriority.HARD:
                hard_failures.append(requirement.key)

        evidence.append(
            RequirementEvidence(
                requirement_key=requirement.key,
                priority=requirement.priority,
                matched=matched,
                fact_key=fact.key,
                evidence_ref=fact.evidence_ref,
                reason=reason,
                fact_value=_safe_fact_value(fact),
            )
        )

    score = round((earned_weight / total_weight) * 100.0, 2)
    return FitScore(
        score=score,
        hard_requirements_met=hard_met,
        hard_requirements_total=hard_total,
        preferred_requirements_met=preferred_met,
        preferred_requirements_total=preferred_total,
        hard_requirement_failures=tuple(hard_failures),
        missing_fact_keys=tuple(sorted(missing_keys)),
        evidence=tuple(evidence),
    )
