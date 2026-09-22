"""Safety regression for event-relative Home/Jarvis physical-memory questions."""

from app.services.home_agent.natural_language import HomeQueryIntent, parse_home_query


def test_departure_relative_queries_fail_closed_until_anchor_is_evidence_backed():
    assert parse_home_query("Where were my keys before I left home?") is None
    assert parse_home_query("Where was my wallet before I departed my home?") is None
    assert parse_home_query("Where did I last see my keys before I left the home?") is None


def test_existing_before_location_query_remains_supported():
    assert parse_home_query("Where were my keys before the kitchen?") == HomeQueryIntent(
        kind="before_location", object_name="keys", location="kitchen"
    )
