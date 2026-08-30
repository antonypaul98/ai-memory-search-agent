"""Production-hardening observability regression tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.middleware.observability import reset_observability_metrics


def test_request_id_generated_and_returned(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    request_id = response.headers.get("x-request-id")
    assert request_id
    assert len(request_id) <= 128


def test_safe_request_id_is_preserved(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "test-run:abc-123"})
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "test-run:abc-123"


def test_unsafe_request_id_is_replaced(client: TestClient) -> None:
    supplied = "bad id\nforged-log-line"
    response = client.get("/api/v1/health", headers={"X-Request-ID": supplied})
    assert response.status_code == 200
    assert response.headers["x-request-id"] != supplied
    assert "\n" not in response.headers["x-request-id"]


def test_metrics_endpoint_exposes_prometheus_text(client: TestClient) -> None:
    reset_observability_metrics()
    response = client.get("/api/v1/health")
    assert response.status_code == 200

    metrics = client.get("/api/v1/metrics")
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain; version=0.0.4")
    body = metrics.text
    assert "# TYPE ai_memory_http_requests_total counter" in body
    assert "ai_memory_http_requests_total " in body
    assert 'ai_memory_http_responses_total{status="200"}' in body
    assert 'ai_memory_route_latency_p95_ms{route="/api/v1/search"}' in body
    assert "# TYPE ai_memory_chat_grounded_rate gauge" in body


def test_metrics_endpoint_uses_only_bounded_non_private_labels(client: TestClient) -> None:
    reset_observability_metrics()
    secretish_request_id = "tenant-123.private-token"
    response = client.get("/api/v1/health", headers={"X-Request-ID": secretish_request_id})
    assert response.status_code == 200

    body = client.get("/api/v1/metrics").text
    assert secretish_request_id not in body
    assert "user_id" not in body
    assert "question" not in body
    assert "canonical_url" not in body


def test_metrics_json_endpoint_preserves_existing_snapshot_contract(client: TestClient) -> None:
    reset_observability_metrics()
    response = client.get("/api/v1/health")
    assert response.status_code == 200

    metrics = client.get("/api/v1/metrics.json")
    assert metrics.status_code == 200
    body = metrics.json()
    # The metrics request itself is still in-flight while its snapshot is built,
    # so the completed health request must be present and counters non-negative.
    assert body["requests_total"] >= 1
    assert body["in_flight"] >= 0
    assert body["status_codes"].get("200", 0) >= 1
    assert body["average_duration_ms"] >= 0
