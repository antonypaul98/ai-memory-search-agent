from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .models import CareerFact, FactSensitivity, MasterCareerProfile


class ResumeChangeKind(str, Enum):
    ADD = "add"
    REMOVE = "remove"
    REORDER = "reorder"


@dataclass(frozen=True, slots=True)
class ResumeChange:
    kind: ResumeChangeKind
    fact_key: str
    before_index: int | None
    after_index: int | None
    evidence_ref: str | None


@dataclass(frozen=True, slots=True)
class TailoredResume:
    tenant_id: str
    target_job_id: str
    role_variant: str | None
    fact_keys: tuple[str, ...]
    facts: tuple[CareerFact, ...]
    changes: tuple[ResumeChange, ...]

    def __post_init__(self) -> None:
        if not self.tenant_id.strip():
            raise ValueError("tenant_id must not be empty")
        if not self.target_job_id.strip():
            raise ValueError("target_job_id must not be empty")
        if self.fact_keys != tuple(fact.key for fact in self.facts):
            raise ValueError("tailored resume fact keys must match resolved canonical facts")


def tailor_resume(
    profile: MasterCareerProfile,
    *,
    target_job_id: str,
    base_fact_keys: Iterable[str],
    selected_fact_keys: Iterable[str] | None = None,
    role_variant: str | None = None,
) -> TailoredResume:
    """Create a deterministic, fact-grounded resume variant.

    The function can select, omit, and reorder existing canonical career facts only.
    It never creates a new career claim from job-description text. Locked facts are
    excluded from resume content because protected application answers belong in a
    separate confirmation-gated path.
    """

    base = tuple(base_fact_keys)
    if len(set(base)) != len(base):
        raise ValueError("base resume fact keys must be unique")

    for key in base:
        profile.resolve_fact(key)

    if selected_fact_keys is None:
        if role_variant is None:
            selected = base
        else:
            selected = tuple(fact.key for fact in profile.resolve_role_variant(role_variant))
    else:
        selected = tuple(selected_fact_keys)

    if len(set(selected)) != len(selected):
        raise ValueError("selected resume fact keys must be unique")

    resolved = tuple(profile.resolve_fact(key) for key in selected)
    locked = [fact.key for fact in resolved if fact.sensitivity is FactSensitivity.LOCKED]
    if locked:
        raise PermissionError(
            "locked facts cannot be rendered into a resume: " + ", ".join(sorted(locked))
        )

    base_index = {key: index for index, key in enumerate(base)}
    selected_index = {key: index for index, key in enumerate(selected)}
    changes: list[ResumeChange] = []

    for key in base:
        if key not in selected_index:
            fact = profile.resolve_fact(key)
            changes.append(
                ResumeChange(
                    kind=ResumeChangeKind.REMOVE,
                    fact_key=key,
                    before_index=base_index[key],
                    after_index=None,
                    evidence_ref=fact.evidence_ref,
                )
            )

    for key in selected:
        fact = profile.resolve_fact(key)
        if key not in base_index:
            changes.append(
                ResumeChange(
                    kind=ResumeChangeKind.ADD,
                    fact_key=key,
                    before_index=None,
                    after_index=selected_index[key],
                    evidence_ref=fact.evidence_ref,
                )
            )
        elif base_index[key] != selected_index[key]:
            changes.append(
                ResumeChange(
                    kind=ResumeChangeKind.REORDER,
                    fact_key=key,
                    before_index=base_index[key],
                    after_index=selected_index[key],
                    evidence_ref=fact.evidence_ref,
                )
            )

    return TailoredResume(
        tenant_id=profile.tenant_id,
        target_job_id=target_job_id,
        role_variant=role_variant,
        fact_keys=selected,
        facts=resolved,
        changes=tuple(changes),
    )
