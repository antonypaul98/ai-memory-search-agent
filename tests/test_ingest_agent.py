"""A-02 Ingest Agent regression tests."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.models.ingest_agent import IngestCandidate, IngestRuleCreate
from app.services.ingest_agent import IngestAgent
from app.services.ingest_service import IngestService


def _rule(agent: IngestAgent, *, user_id: str = "user-a"):
    return agent.create_rule(
        user_id=user_id,
        request=IngestRuleCreate(
            name="Auto-ingest channel X",
            connector_id="youtube.v1",
            match={"channel_id": "channel-x"},
        ),
    )


def test_rule_requires_explicit_user_approval(test_settings: Settings) -> None:
    agent = IngestAgent(test_settings)
    rule = _rule(agent)
    assert rule.approved is False
    assert rule.enabled is False

    with pytest.raises(PermissionError):
        agent.run_rule(
            user_id="user-a",
            rule_id=rule.rule_id,
            candidates=[
                IngestCandidate(
                    url="https://youtu.be/dQw4w9WgXcQ",
                    attributes={"channel_id": "channel-x"},
                )
            ],
        )


def test_approved_rule_matches_connector_metadata_and_dedupes(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, bool]] = []

    def fake_ingest(self, url: str, *, user_id: str, force_refresh: bool = False):
        calls.append((url, user_id, force_refresh))
        return object()

    monkeypatch.setattr(IngestService, "ingest_single_url", fake_ingest)
    agent = IngestAgent(test_settings)
    rule = agent.approve_rule(user_id="user-a", rule_id=_rule(agent).rule_id)

    out = agent.run_rule(
        user_id="user-a",
        rule_id=rule.rule_id,
        candidates=[
            IngestCandidate(
                url="https://youtu.be/dQw4w9WgXcQ",
                attributes={"channel_id": "channel-x"},
            ),
            IngestCandidate(
                url="https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=20",
                attributes={"channel_id": "channel-x"},
            ),
            IngestCandidate(
                url="https://youtu.be/9bZkp7q19f0",
                attributes={"channel_id": "different-channel"},
            ),
        ],
    )

    assert out.ingested == 1
    assert out.duplicates == 1
    assert out.skipped == 1
    assert calls == [("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "user-a", False)]

    again = agent.run_rule(
        user_id="user-a",
        rule_id=rule.rule_id,
        candidates=[
            IngestCandidate(
                url="https://youtu.be/dQw4w9WgXcQ",
                attributes={"channel_id": "channel-x"},
            )
        ],
    )
    assert again.duplicates == 1
    assert len(calls) == 1


def test_rule_and_claims_are_tenant_scoped(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_ingest(self, url: str, *, user_id: str, force_refresh: bool = False):
        calls.append(user_id)
        return object()

    monkeypatch.setattr(IngestService, "ingest_single_url", fake_ingest)
    agent = IngestAgent(test_settings)
    rule = agent.approve_rule(user_id="user-a", rule_id=_rule(agent).rule_id)

    with pytest.raises(KeyError):
        agent.get_rule(user_id="user-b", rule_id=rule.rule_id)
    with pytest.raises(KeyError):
        agent.run_rule(
            user_id="user-b",
            rule_id=rule.rule_id,
            candidates=[IngestCandidate(url="https://youtu.be/dQw4w9WgXcQ")],
        )
    assert calls == []


def test_failed_ingest_releases_claim_for_safe_retry(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def flaky_ingest(self, url: str, *, user_id: str, force_refresh: bool = False):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary failure")
        return object()

    monkeypatch.setattr(IngestService, "ingest_single_url", flaky_ingest)
    agent = IngestAgent(test_settings)
    rule = agent.approve_rule(user_id="user-a", rule_id=_rule(agent).rule_id)
    candidate = IngestCandidate(
        url="https://youtu.be/dQw4w9WgXcQ",
        attributes={"channel_id": "channel-x"},
    )

    first = agent.run_rule(user_id="user-a", rule_id=rule.rule_id, candidates=[candidate])
    second = agent.run_rule(user_id="user-a", rule_id=rule.rule_id, candidates=[candidate])

    assert first.failed == 1
    assert second.ingested == 1
    assert attempts == 2


def test_connector_mismatch_and_unsafe_url_never_ingest(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_ingest(*args, **kwargs):
        raise AssertionError("ingest must not be called")

    monkeypatch.setattr(IngestService, "ingest_single_url", forbidden_ingest)
    agent = IngestAgent(test_settings)
    rule = agent.approve_rule(user_id="user-a", rule_id=_rule(agent).rule_id)

    out = agent.run_rule(
        user_id="user-a",
        rule_id=rule.rule_id,
        candidates=[
            IngestCandidate(url="https://example.com/article", attributes={"channel_id": "channel-x"}),
            IngestCandidate(url="file:///etc/passwd", attributes={"channel_id": "channel-x"}),
        ],
    )

    assert out.skipped == 1
    assert out.rejected == 1
