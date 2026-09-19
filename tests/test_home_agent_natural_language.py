"""Tests for deterministic Home/Jarvis physical-memory query routing."""
from app.services.home_agent.natural_language import HomeQueryIntent, parse_home_query


def test_routes_current_location_question():
    assert parse_home_query("Where are my keys?") == HomeQueryIntent(kind="where_is", object_name="keys")


def test_routes_direct_before_location_question():
    assert parse_home_query("Where were my keys before the kitchen?") == HomeQueryIntent(
        kind="before_location", object_name="keys", location="kitchen"
    )


def test_routes_natural_left_them_before_location_question():
    assert parse_home_query("  Where were my keys before I left them in the kitchen?  ") == HomeQueryIntent(
        kind="before_location", object_name="keys", location="kitchen"
    )


def test_routes_singular_object_before_location_question():
    assert parse_home_query("Where was the wallet before I put it on the entry table?") == HomeQueryIntent(
        kind="before_location", object_name="wallet", location="entry table"
    )


def test_unknown_language_fails_closed():
    assert parse_home_query("Did anyone move my keys after lunch?") is None
    assert parse_home_query("") is None
