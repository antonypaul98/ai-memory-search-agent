"""Regression tests for tenant-scoped recommendations and chat usage."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.api.routes.usage import list_recommendations
from app.config import Settings
from app.models.user import UserPublic
from app.services.chat_service import ChatService
from app.services.recommendation_service import RecommendationService


def test_recommendation_search_is_scoped_to_requested_user() -> None:
    repository = MagicMock()
    repository.search.return_value = []
    registry = MagicMock()
    service = RecommendationService(
        settings=Settings(), repository=repository, registry=registry
    )

    with patch("app.services.recommendation_service.embed_query", return_value=[0.1, 0.2]):
        service.recommend_for_query("docker", user_id="tenant-a")

    repository.search.assert_called_once()
    assert repository.search.call_args.kwargs["user_id"] == "tenant-a"


def test_recommendation_reflection_lookup_is_scoped_to_requested_user() -> None:
    repository = MagicMock()
    repository.search.return_value = [
        {
            "video_id": "vid-1",
            "title": "Docker",
            "channel": "Demo",
            "thumbnail": "",
            "url": "https://example.test/1",
            "relevance_score": 0.8,
        }
    ]
    registry = MagicMock()
    registry.get_video.return_value = {
        "recommendations_enabled": True,
        "preferred_creator_only": False,
        "goal": "containers",
    }
    service = RecommendationService(
        settings=Settings(), repository=repository, registry=registry
    )

    with patch("app.services.recommendation_service.embed_query", return_value=[0.1, 0.2]):
        result = service.recommend_for_query("docker", user_id="tenant-b")

    assert len(result) == 1
    registry.get_video.assert_called_once_with("vid-1", user_id="tenant-b")


def test_recommendation_api_passes_authenticated_user_to_service() -> None:
    service = MagicMock()
    service.recommend_for_query.return_value = []
    user = UserPublic(user_id="tenant-c", display_name="Tenant C")

    result = list_recommendations(q="rag", limit=2, service=service, user=user)

    assert result == []
    service.recommend_for_query.assert_called_once_with(
        "rag", limit=2, user_id="tenant-c"
    )


def test_chat_propagates_tenant_to_usage_and_recommendations() -> None:
    ahme = MagicMock()
    ahme.retrieve.return_value = (
        [
            {
                "video_id": "vid-1",
                "title": "Demo",
                "url": "https://www.youtube.com/watch?v=vid-1",
                "start_time": 0.0,
                "end_time": 10.0,
                "matched_text": "relevant evidence",
                "relevance_score": 0.9,
            }
        ],
        SimpleNamespace(synthesis_ms=0.0, estimated_llm_tokens=0),
    )
    registry = MagicMock()
    recommendations = MagicMock()
    recommendations.recommend_for_query.return_value = []
    service = ChatService(
        settings=Settings(),
        repository=MagicMock(),
        registry=registry,
        recommendation_service=recommendations,
        ahme=ahme,
    )
    generated = SimpleNamespace(answer="Grounded answer", grounded=True)

    with (
        patch(
            "app.services.chat_service.analyze_clarification",
            return_value=SimpleNamespace(needs_clarification=False, options=[]),
        ),
        patch(
            "app.services.chat_service.synthesize_grounded_answer",
            return_value=(generated, "high", 1.0),
        ),
    ):
        response = service.chat("What did I save?", user_id="tenant-d")

    assert response.grounded is True
    registry.record_search.assert_called_once_with(["vid-1"], user_id="tenant-d")
    recommendations.recommend_for_query.assert_called_once()
    assert recommendations.recommend_for_query.call_args.kwargs["user_id"] == "tenant-d"
