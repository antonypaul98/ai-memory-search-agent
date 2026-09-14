from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import re

_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "referrer",
    "source",
}
_TRACKING_PREFIXES = ("utm_",)
_WHITESPACE_RE = re.compile(r"\s+")


def _normalized_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _WHITESPACE_RE.sub(" ", value).strip()
    return normalized or None


def _identity_text(value: str | None) -> str:
    normalized = _normalized_text(value)
    return normalized.casefold() if normalized else ""


def canonicalize_job_url(url: str | None) -> str | None:
    normalized = _normalized_text(url)
    if normalized is None:
        return None

    parts = urlsplit(normalized)
    if not parts.scheme or not parts.netloc:
        raise ValueError("job source_url must be absolute")

    scheme = parts.scheme.casefold()
    if scheme not in {"http", "https"}:
        raise ValueError("job source_url must use http or https")

    host = (parts.hostname or "").casefold()
    if not host:
        raise ValueError("job source_url must include a hostname")
    port = parts.port
    default_port = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    netloc = host if port is None or default_port else f"{host}:{port}"

    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")

    clean_query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        folded = key.casefold()
        if folded in _TRACKING_QUERY_KEYS or any(folded.startswith(prefix) for prefix in _TRACKING_PREFIXES):
            continue
        clean_query.append((key, value))
    clean_query.sort(key=lambda item: (item[0].casefold(), item[1]))

    return urlunsplit((scheme, netloc, path, urlencode(clean_query, doseq=True), ""))


@dataclass(frozen=True, slots=True)
class JobSource:
    provider: str
    source_url: str | None = None
    external_id: str | None = None
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        provider = _normalized_text(self.provider)
        if provider is None:
            raise ValueError("job source provider must not be empty")
        object.__setattr__(self, "provider", provider.casefold())
        object.__setattr__(self, "source_url", canonicalize_job_url(self.source_url))
        object.__setattr__(self, "external_id", _normalized_text(self.external_id))
        object.__setattr__(self, "evidence_ref", _normalized_text(self.evidence_ref))
        if self.source_url is None and self.external_id is None:
            raise ValueError("job source requires source_url or external_id")


@dataclass(frozen=True, slots=True)
class NormalizedJob:
    tenant_id: str
    title: str
    company: str
    location: str | None
    description: str
    source: JobSource
    employment_type: str | None = None
    remote_policy: str | None = None

    def __post_init__(self) -> None:
        tenant_id = _normalized_text(self.tenant_id)
        title = _normalized_text(self.title)
        company = _normalized_text(self.company)
        description = _normalized_text(self.description)
        if tenant_id is None:
            raise ValueError("tenant_id must not be empty")
        if title is None:
            raise ValueError("job title must not be empty")
        if company is None:
            raise ValueError("job company must not be empty")
        if description is None:
            raise ValueError("job description must not be empty")
        object.__setattr__(self, "tenant_id", tenant_id)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "company", company)
        object.__setattr__(self, "location", _normalized_text(self.location))
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "employment_type", _normalized_text(self.employment_type))
        object.__setattr__(self, "remote_policy", _normalized_text(self.remote_policy))

    @property
    def fingerprint(self) -> str:
        if self.source.external_id:
            identity = (
                "external",
                self.source.provider,
                self.source.external_id.casefold(),
            )
        elif self.source.source_url:
            identity = ("url", self.source.source_url)
        else:  # guarded by JobSource validation
            identity = (
                "fallback",
                _identity_text(self.company),
                _identity_text(self.title),
                _identity_text(self.location),
            )
        payload = "\x1f".join(identity).encode("utf-8")
        return sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class JobImportResult:
    job: NormalizedJob
    created: bool
    duplicate_of_fingerprint: str | None = None


@dataclass(slots=True)
class JobRegistry:
    """In-memory canonicalization boundary; persistence adapters can mirror this contract."""

    _jobs_by_tenant: dict[str, dict[str, NormalizedJob]] = field(default_factory=dict)

    def import_job(self, job: NormalizedJob) -> JobImportResult:
        tenant_jobs = self._jobs_by_tenant.setdefault(job.tenant_id, {})
        fingerprint = job.fingerprint
        existing = tenant_jobs.get(fingerprint)
        if existing is not None:
            return JobImportResult(
                job=existing,
                created=False,
                duplicate_of_fingerprint=fingerprint,
            )
        tenant_jobs[fingerprint] = job
        return JobImportResult(job=job, created=True)

    def import_many(self, jobs: Iterable[NormalizedJob]) -> tuple[JobImportResult, ...]:
        return tuple(self.import_job(job) for job in jobs)

    def get(self, tenant_id: str, fingerprint: str) -> NormalizedJob:
        tenant_key = _normalized_text(tenant_id)
        if tenant_key is None:
            raise ValueError("tenant_id must not be empty")
        try:
            return self._jobs_by_tenant[tenant_key][fingerprint]
        except KeyError as exc:
            raise KeyError("unknown tenant-scoped job fingerprint") from exc

    def list_for_tenant(self, tenant_id: str) -> tuple[NormalizedJob, ...]:
        tenant_key = _normalized_text(tenant_id)
        if tenant_key is None:
            raise ValueError("tenant_id must not be empty")
        jobs = self._jobs_by_tenant.get(tenant_key, {})
        return tuple(jobs[key] for key in sorted(jobs))
