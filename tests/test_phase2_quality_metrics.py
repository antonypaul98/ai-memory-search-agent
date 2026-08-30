"""Phase 2 quality/latency observability regression tests."""

from app.middleware.observability import (
    _record_finish,
    metrics_snapshot,
    record_chat_outcome,
    reset_observability_metrics,
)


def setup_function() -> None:
    reset_observability_metrics()


def teardown_function() -> None:
    reset_observability_metrics()


def test_search_latency_exposes_count_average_and_p95() -> None:
    for duration in (10.0, 20.0, 30.0, 40.0, 100.0):
        _record_finish(200, duration, "/api/v1/search")

    search = metrics_snapshot()["route_latency"]["/api/v1/search"]
    assert search == {"count": 5, "average_ms": 40.0, "p95_ms": 100.0}


def test_untracked_routes_do_not_create_high_cardinality_latency_metrics() -> None:
    _record_finish(200, 12.0, "/api/v1/memories/arbitrary-id")

    metrics = metrics_snapshot()
    assert set(metrics["route_latency"]) == {"/api/v1/chat", "/api/v1/search"}
    assert metrics["route_latency"]["/api/v1/search"]["count"] == 0
    assert metrics["route_latency"]["/api/v1/chat"]["count"] == 0


def test_grounded_rate_excludes_clarification_only_responses() -> None:
    record_chat_outcome(grounded=True, needs_clarification=False)
    record_chat_outcome(grounded=False, needs_clarification=False)
    record_chat_outcome(grounded=False, needs_clarification=True)

    quality = metrics_snapshot()["chat_quality"]
    assert quality == {
        "total": 3,
        "answered_total": 2,
        "grounded_total": 1,
        "clarification_total": 1,
        "grounded_rate": 0.5,
    }


def test_metrics_json_endpoint_exposes_only_aggregate_quality_data(client) -> None:
    record_chat_outcome(grounded=True, needs_clarification=False)
    _record_finish(200, 25.0, "/api/v1/search")

    response = client.get("/api/v1/metrics.json")
    assert response.status_code == 200
    data = response.json()
    assert data["chat_quality"]["grounded_rate"] == 1.0
    assert data["route_latency"]["/api/v1/search"]["p95_ms"] == 25.0
    serialized = response.text
    assert "private question text" not in serialized
    assert "private answer text" not in serialized


def test_chat_api_records_quality_outcome(client) -> None:
    response = client.post(
        "/api/v1/chat",
        json={"question": "What did I save about a topic with no memories?"},
    )
    assert response.status_code == 200

    quality = metrics_snapshot()["chat_quality"]
    assert quality["total"] == 1
    assert quality["answered_total"] == 1
    assert quality["grounded_total"] in {0, 1}
    assert 0.0 <= quality["grounded_rate"] <= 1.0
