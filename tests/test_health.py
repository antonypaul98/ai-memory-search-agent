"""Tests for health, liveness, and readiness endpoints."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.core.exceptions import ChromaConnectionError


class TestHealthEndpoint:
    def test_liveness_does_not_require_storage_dependencies(self, client: TestClient) -> None:
        with (
            patch(
                "app.services.health_service.MemoryRepository.check_connection",
                side_effect=ChromaConnectionError("Chroma down"),
            ),
            patch(
                "app.services.health_service.get_postgres_connection_factory",
                side_effect=RuntimeError("Postgres down"),
            ),
        ):
            response = client.get("/api/v1/live")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_readiness_returns_ok(self, client: TestClient) -> None:
        response = client.get("/api/v1/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["app_name"] == "AI Memory Search Agent (test)"
        assert data["chroma"]["connected"] is True

    def test_readiness_returns_503_when_chroma_fails(self, client: TestClient) -> None:
        with patch(
            "app.services.health_service.MemoryRepository.check_connection",
            side_effect=ChromaConnectionError("Chroma down"),
        ):
            response = client.get("/api/v1/ready")
        assert response.status_code == 503
        assert "Chroma down" in response.json()["detail"]

    def test_production_readiness_probes_postgres(self, client: TestClient) -> None:
        connection = MagicMock()
        connection.__enter__.return_value.execute.return_value.fetchone.return_value = {"ready": 1}
        factory = MagicMock(return_value=connection)

        with (
            patch("app.services.health_service.is_complete_postgres_profile", return_value=True),
            patch("app.services.health_service.get_postgres_connection_factory", return_value=factory),
        ):
            response = client.get("/api/v1/ready")

        assert response.status_code == 200
        factory.assert_called_once_with()
        connection.__enter__.return_value.execute.assert_called_once_with("SELECT 1 AS ready")

    def test_production_readiness_hides_postgres_connection_details(self, client: TestClient) -> None:
        leaked_detail = "could not connect to postgresql://secret:password@private-db.internal/memory"
        with (
            patch("app.services.health_service.is_complete_postgres_profile", return_value=True),
            patch(
                "app.services.health_service.get_postgres_connection_factory",
                side_effect=RuntimeError(leaked_detail),
            ),
        ):
            response = client.get("/api/v1/ready")

        assert response.status_code == 503
        assert response.json()["detail"] == "Postgres is not ready"
        assert "secret" not in response.text
        assert "private-db" not in response.text

    def test_local_readiness_does_not_probe_postgres(self, client: TestClient) -> None:
        with (
            patch("app.services.health_service.is_complete_postgres_profile", return_value=False),
            patch("app.services.health_service.get_postgres_connection_factory") as postgres_factory,
        ):
            response = client.get("/api/v1/ready")

        assert response.status_code == 200
        postgres_factory.assert_not_called()

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
