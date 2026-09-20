"""Tests for authenticated execution of bounded Home/Jarvis questions."""
from unittest.mock import MagicMock

from app.models.user import UserPublic
from app.services.home_agent.authenticated_query import AuthenticatedHomeAgentQuery
from app.services.home_agent.natural_language_query import execute_home_query
from app.services.home_agent.query_service import BeforeLocationAnswer, HomeAgentQueryService, MovementEvent, WhereAnswer


def _query(service):
    return AuthenticatedHomeAgentQuery(
        service=service,
        user=UserPublic(user_id="owner-a", display_name="Owner A"),
    )


def test_executes_where_is_with_authenticated_identity():
    service = MagicMock(spec=HomeAgentQueryService)
    service.where_is.return_value = WhereAnswer(
        object_name="keys", location="desk", observed_at="2026-09-19T14:00:00+00:00",
        confidence=0.94, source_id="camera-office", evidence_id="frame-desk",
    )
    result = execute_home_query(text="Where are my keys?", query=_query(service), min_confidence=0.8)
    assert result.status == "answered"
    assert result.kind == "where_is"
    assert result.answer is service.where_is.return_value
    service.where_is.assert_called_once_with(user_id="owner-a", object_name="keys", min_confidence=0.8)


def test_executes_before_location_and_preserves_evidence():
    service = MagicMock(spec=HomeAgentQueryService)
    service.before_location.return_value = BeforeLocationAnswer(
        object_name="keys", location="hall", before_location="kitchen",
        moved_at="2026-09-19T14:00:00+00:00", confidence=0.95,
        source_id="camera-kitchen", evidence_id="frame-hall",
        destination_evidence_id="frame-kitchen",
    )
    result = execute_home_query(
        text="Where were my keys before I left them in the kitchen?",
        query=_query(service), min_confidence=0.7, limit=12,
    )
    assert result.status == "answered"
    assert result.kind == "before_location"
    assert result.answer.evidence_id == "frame-hall"
    assert result.answer.destination_evidence_id == "frame-kitchen"
    service.before_location.assert_called_once_with(
        user_id="owner-a", object_name="keys", location="kitchen",
        min_confidence=0.7, limit=12,
    )


def test_executes_location_history_with_authenticated_identity_and_evidence():
    service = MagicMock(spec=HomeAgentQueryService)
    service.movement_history.return_value = [MovementEvent(
        object_name="keys", from_location="desk", to_location="kitchen",
        moved_at="2026-09-19T15:00:00+00:00", confidence=0.93,
        source_id="camera-kitchen", from_evidence_id="frame-desk",
        to_evidence_id="frame-kitchen",
    )]
    result = execute_home_query(
        text="Where have my keys been?", query=_query(service), min_confidence=0.8, limit=12,
    )
    assert result.status == "answered"
    assert result.kind == "location_history"
    assert result.answer == service.movement_history.return_value
    assert result.answer[0].from_evidence_id == "frame-desk"
    assert result.answer[0].to_evidence_id == "frame-kitchen"
    service.movement_history.assert_called_once_with(
        user_id="owner-a", object_name="keys", min_confidence=0.8, limit=12,
        since=None, until=None,
    )


def test_empty_location_history_returns_not_found():
    service = MagicMock(spec=HomeAgentQueryService)
    service.movement_history.return_value = []
    result = execute_home_query(text="Where has my wallet been?", query=_query(service))
    assert result.status == "not_found"
    assert result.kind == "location_history"


def test_unsupported_language_fails_closed_without_querying_store():
    service = MagicMock(spec=HomeAgentQueryService)
    result = execute_home_query(text="Did someone move my keys after lunch?", query=_query(service))
    assert result.status == "unsupported"
    service.where_is.assert_not_called()
    service.before_location.assert_not_called()
    service.movement_history.assert_not_called()


def test_supported_question_without_memory_returns_not_found():
    service = MagicMock(spec=HomeAgentQueryService)
    service.where_is.return_value = None
    result = execute_home_query(text="Where is my wallet?", query=_query(service))
    assert result.status == "not_found"
    assert result.kind == "where_is"
