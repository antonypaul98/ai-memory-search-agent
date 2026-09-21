"""End-to-end routing coverage for local-day Home Agent questions."""
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.home_agent.natural_language import parse_home_query
from app.services.home_agent.natural_language_query import execute_home_query


class _Query:
    def __init__(self):
        self.user = SimpleNamespace(timezone_name="America/New_York")
        self.calls = []

    def where_is_today(self, **kwargs):
        self.calls.append(("where_is_today", kwargs))
        return SimpleNamespace(location="entry table", evidence_id="frame-today")

    def where_is(self, **kwargs):
        self.calls.append(("where_is", kwargs))
        return SimpleNamespace(location="garage", evidence_id="frame-latest")

    def movement_history(self, **kwargs):
        self.calls.append(("movement_history", kwargs))
        return [SimpleNamespace(location="entry table")]


def test_parser_separates_today_from_object_name():
    intent = parse_home_query("Where did I last see my keys today?")
    assert intent is None  # unsupported phrasing remains fail-closed until explicitly modeled

    intent = parse_home_query("Where are my keys today?")
    assert intent is not None
    assert intent.kind == "where_is"
    assert intent.object_name == "keys"
    assert intent.time_scope == "today"


def test_today_last_seen_routes_to_authenticated_local_day_path():
    query = _Query()
    now = datetime(2026, 9, 21, 4, 30, tzinfo=timezone.utc)
    result = execute_home_query(
        text="Where are my keys today?",
        query=query,
        timezone_name="Asia/Tokyo",  # caller input must not control authenticated relative time
        now=now,
    )
    assert result.status == "answered"
    assert query.calls[0][0] == "where_is_today"
    assert query.calls[0][1]["object_name"] == "keys"
    assert query.calls[0][1]["now"] == now


def test_today_history_uses_authenticated_timezone_not_caller_timezone():
    query = _Query()
    now = datetime(2026, 9, 21, 4, 30, tzinfo=timezone.utc)
    result = execute_home_query(
        text="Where have my keys been today?",
        query=query,
        timezone_name="Asia/Tokyo",
        now=now,
    )
    assert result.status == "answered"
    _, kwargs = query.calls[0]
    assert kwargs["since"] == datetime(2026, 9, 21, 4, 0, tzinfo=timezone.utc)
    assert kwargs["until"] == datetime(2026, 9, 22, 4, 0, tzinfo=timezone.utc)
