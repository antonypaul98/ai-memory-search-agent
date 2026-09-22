"""Regression coverage for yesterday-scoped Home Agent physical memory."""
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.home_agent.natural_language import parse_home_query
from app.services.home_agent.natural_language_query import execute_home_query


class _Query:
    def __init__(self):
        self.user = SimpleNamespace(timezone_name="America/New_York")
        self.calls = []

    def movement_history(self, **kwargs):
        self.calls.append(("movement_history", kwargs))
        return [SimpleNamespace(location="desk", evidence_id="frame-yesterday")]

    def where_is(self, **kwargs):
        self.calls.append(("where_is", kwargs))
        return SimpleNamespace(location="garage", evidence_id="frame-latest")


def test_parser_separates_yesterday_from_object_name():
    for text in ("Where did I last see my keys yesterday?", "Where were my keys yesterday?"):
        intent = parse_home_query(text)
        assert intent is not None
        assert intent.kind == "where_is"
        assert intent.object_name == "keys"
        assert intent.time_scope == "yesterday"


def test_yesterday_last_seen_uses_authenticated_local_day():
    query = _Query()
    now = datetime(2026, 11, 2, 5, 30, tzinfo=timezone.utc)
    result = execute_home_query(
        text="Where did I last see my keys yesterday?",
        query=query,
        timezone_name="Asia/Tokyo",
        now=now,
    )
    assert result.status == "answered"
    assert result.answer.location == "desk"
    _, kwargs = query.calls[0]
    # 2026-11-01 is the DST fall-back day in New York: a 25-hour local day.
    assert kwargs["since"] == datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc)
    assert kwargs["until"] == datetime(2026, 11, 2, 5, 0, tzinfo=timezone.utc)


def test_yesterday_history_uses_authenticated_timezone():
    query = _Query()
    now = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
    result = execute_home_query(
        text="Where have my keys been yesterday?",
        query=query,
        timezone_name="Asia/Tokyo",
        now=now,
    )
    assert result.status == "answered"
    _, kwargs = query.calls[0]
    assert kwargs["since"] == datetime(2026, 9, 21, 4, 0, tzinfo=timezone.utc)
    assert kwargs["until"] == datetime(2026, 9, 22, 4, 0, tzinfo=timezone.utc)
