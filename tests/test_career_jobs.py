from __future__ import annotations

import pytest

from app.career.jobs import JobRegistry, JobSource, NormalizedJob, canonicalize_job_url


def _job(*, tenant_id: str = "tenant-a", source: JobSource | None = None) -> NormalizedJob:
    return NormalizedJob(
        tenant_id=tenant_id,
        title="  Senior   QA Engineer ",
        company=" Example   Corp ",
        location=" Remote  - US ",
        description=" Test   automation and API validation. ",
        source=source
        or JobSource(
            provider="LinkedIn",
            source_url="HTTPS://Jobs.Example.com/roles/123/?utm_source=linkedin&b=2&a=1#apply",
        ),
        employment_type=" Full time ",
        remote_policy=" Remote ",
    )


def test_canonicalize_job_url_removes_tracking_fragment_and_sorts_query() -> None:
    assert canonicalize_job_url(
        "HTTPS://Jobs.Example.com:443//roles/123/?utm_source=x&b=2&a=1#apply"
    ) == "https://jobs.example.com/roles/123?a=1&b=2"


def test_job_source_requires_stable_locator() -> None:
    with pytest.raises(ValueError, match="requires source_url or external_id"):
        JobSource(provider="linkedin")


def test_normalized_job_collapses_whitespace_without_rewriting_meaning() -> None:
    job = _job()
    assert job.title == "Senior QA Engineer"
    assert job.company == "Example Corp"
    assert job.description == "Test automation and API validation."


def test_same_canonical_url_deduplicates_tracking_variants() -> None:
    registry = JobRegistry()
    first = _job()
    duplicate = _job(
        source=JobSource(
            provider="linkedin",
            source_url="https://jobs.example.com/roles/123?a=1&b=2&utm_campaign=fall",
        )
    )

    created = registry.import_job(first)
    deduped = registry.import_job(duplicate)

    assert created.created is True
    assert deduped.created is False
    assert deduped.job is first
    assert deduped.duplicate_of_fingerprint == first.fingerprint


def test_external_id_is_provider_scoped_and_stable() -> None:
    first = _job(source=JobSource(provider="Greenhouse", external_id=" JOB-42 "))
    duplicate = _job(
        source=JobSource(
            provider="greenhouse",
            external_id="job-42",
            source_url="https://boards.example.com/jobs/42?utm_source=email",
        )
    )
    other_provider = _job(source=JobSource(provider="lever", external_id="job-42"))

    assert first.fingerprint == duplicate.fingerprint
    assert first.fingerprint != other_provider.fingerprint


def test_deduplication_is_tenant_scoped() -> None:
    registry = JobRegistry()
    tenant_a = _job(tenant_id="tenant-a")
    tenant_b = _job(tenant_id="tenant-b")

    assert registry.import_job(tenant_a).created is True
    assert registry.import_job(tenant_b).created is True
    assert registry.get("tenant-a", tenant_a.fingerprint).tenant_id == "tenant-a"
    assert registry.get("tenant-b", tenant_b.fingerprint).tenant_id == "tenant-b"


def test_cross_tenant_lookup_is_rejected() -> None:
    registry = JobRegistry()
    job = _job(tenant_id="tenant-a")
    registry.import_job(job)

    with pytest.raises(KeyError, match="unknown tenant-scoped job fingerprint"):
        registry.get("tenant-b", job.fingerprint)


def test_import_many_reports_duplicates_deterministically() -> None:
    registry = JobRegistry()
    first = _job(source=JobSource(provider="ashby", external_id="A-1"))
    duplicate = _job(source=JobSource(provider="ASHBY", external_id="a-1"))

    results = registry.import_many([first, duplicate])

    assert [result.created for result in results] == [True, False]
    assert len(registry.list_for_tenant("tenant-a")) == 1
