"""Jarvis voice transcript API tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_voice_plan_normalizes_wake_phrase(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/jarvis/voice",
        json={"text": "Hey Jarvis, search MCP servers", "execute": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["executed"] is False
    assert data["status"] == "planned"
    assert data["plan"]["intent"] == "search"
    assert data["plan"]["query"] == "MCP servers"


def test_voice_rejects_missing_wake_phrase(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/jarvis/voice",
        json={"text": "search MCP servers", "execute": False},
    )
    assert resp.status_code == 400
    assert "wake phrase" in resp.json()["detail"].lower()


def test_voice_rejects_wake_only(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/jarvis/voice",
        json={"text": "Jarvis", "execute": False},
    )
    assert resp.status_code == 400
    assert "command required" in resp.json()["detail"].lower()


def test_voice_keeps_bulk_confirmation_gate(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/jarvis/voice",
        json={"text": "Jarvis, import bookmarks", "execute": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["executed"] is False
    assert data["status"] == "confirm_required"
    assert data["plan"]["requires_confirm"] is True
    assert data["plan"]["confirm_token"]
