"""A-02 Ingest Agent API confirmation-boundary regression tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services.ingest_service import IngestService


def test_ingest_rule_api_requires_separate_approval_before_run(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_ingest(self, url: str, *, user_id: str, force_refresh: bool = False):
        calls.append(url)
        return object()

    monkeypatch.setattr(IngestService, "ingest_single_url", fake_ingest)

    created = client.post(
        "/api/v1/agents/ingest/rules",
        json={
            "name": "Auto-ingest channel X",
            "connector_id": "youtube.v1",
            "match": {"channel_id": "channel-x"},
        },
    )
    assert created.status_code == 200
    rule = created.json()
    assert rule["approved"] is False
    assert rule["enabled"] is False

    payload = {
        "candidates": [
            {
                "url": "https://youtu.be/dQw4w9WgXcQ",
                "attributes": {"channel_id": "channel-x"},
            }
        ]
    }
    blocked = client.post(f"/api/v1/agents/ingest/rules/{rule['rule_id']}/run", json=payload)
    assert blocked.status_code == 403
    assert calls == []

    approved = client.post(f"/api/v1/agents/ingest/rules/{rule['rule_id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["approved"] is True
    assert approved.json()["enabled"] is True

    run = client.post(f"/api/v1/agents/ingest/rules/{rule['rule_id']}/run", json=payload)
    assert run.status_code == 200
    assert run.json()["ingested"] == 1
    assert calls == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]
