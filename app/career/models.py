from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class FactSensitivity(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    LOCKED = "locked"


class FactSource(str, Enum):
    USER = "user"
    RESUME = "resume"
    APPLICATION = "application"
    RECRUITER = "recruiter"
    IMPORT = "import"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class CareerFact:
    key: str
    value: Any
    source: FactSource
    sensitivity: FactSensitivity = FactSensitivity.PUBLIC
    evidence_ref: str | None = None
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("career fact key must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.sensitivity is FactSensitivity.LOCKED and self.source is FactSource.SYSTEM:
            raise ValueError("locked career facts must be grounded in non-system evidence")


@dataclass(frozen=True, slots=True)
class RoleVariant:
    name: str
    fact_keys: tuple[str, ...]
    summary: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("role variant name must not be empty")
        if not self.fact_keys:
            raise ValueError("role variant must reference at least one canonical fact")
        if len(set(self.fact_keys)) != len(self.fact_keys):
            raise ValueError("role variant fact keys must be unique")


@dataclass(slots=True)
class MasterCareerProfile:
    tenant_id: str
    facts: dict[str, CareerFact] = field(default_factory=dict)
    role_variants: dict[str, RoleVariant] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tenant_id.strip():
            raise ValueError("tenant_id must not be empty")

    def add_fact(self, fact: CareerFact, *, replace: bool = False) -> None:
        existing = self.facts.get(fact.key)
        if existing is not None and not replace:
            raise ValueError(f"career fact already exists: {fact.key}")
        if existing is not None and existing.sensitivity is FactSensitivity.LOCKED:
            if fact.value != existing.value:
                raise PermissionError(f"locked career fact cannot be changed implicitly: {fact.key}")
        self.facts[fact.key] = fact

    def add_role_variant(self, variant: RoleVariant) -> None:
        missing = sorted(set(variant.fact_keys) - self.facts.keys())
        if missing:
            raise ValueError(f"role variant references unknown facts: {', '.join(missing)}")
        self.role_variants[variant.name] = variant

    def resolve_fact(self, key: str) -> CareerFact:
        try:
            return self.facts[key]
        except KeyError as exc:
            raise KeyError(f"unknown canonical career fact: {key}") from exc

    def resolve_role_variant(self, name: str) -> tuple[CareerFact, ...]:
        try:
            variant = self.role_variants[name]
        except KeyError as exc:
            raise KeyError(f"unknown role variant: {name}") from exc
        return tuple(self.facts[key] for key in variant.fact_keys)

    def require_locked_facts(self, keys: Iterable[str]) -> dict[str, CareerFact]:
        resolved: dict[str, CareerFact] = {}
        for key in keys:
            fact = self.resolve_fact(key)
            if fact.sensitivity is not FactSensitivity.LOCKED:
                raise PermissionError(f"fact is not locked and cannot be used as a protected answer: {key}")
            resolved[key] = fact
        return resolved
