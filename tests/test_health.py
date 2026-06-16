"""Tests for GET /api/v1/health."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.exceptions import ChromaConnectionError


class TestHealthEndpoint:
    def test_health_returns_ok(self, client: TestClient) -> None:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["app_name"] == "AI Memory Search Agent (test)"
        assert data["chroma"]["connected"] is True
        assert data["chroma"]["collection"] == "test_memory_items"
        assert data["chroma"]["document_count"] == 0

    def test_health_returns_503_when_chroma_fails(self, client: TestClient) -> None:
        with patch(
            "app.services.health_service.MemoryRepository.check_connection",
            side_effect=ChromaConnectionError("Chroma down"),
        ):
            response = client.get("/api/v1/health")
        assert response.status_code == 503
        assert "Chroma down" in response.json()["detail"]
