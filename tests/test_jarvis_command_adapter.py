"""Jarvis spoken-command adapter tests."""

from app.services.jarvis_command_adapter import (
    has_jarvis_wake_phrase,
    normalize_jarvis_command,
)


def test_strips_plain_wake_word() -> None:
    assert normalize_jarvis_command("Jarvis, search MCP servers") == "search MCP servers"


def test_strips_friendly_wake_phrase_case_insensitively() -> None:
    assert (
        normalize_jarvis_command("hey JARVIS tell me what I saved about Docker")
        == "tell me what I saved about Docker"
    )


def test_non_jarvis_text_is_preserved_except_outer_whitespace() -> None:
    assert normalize_jarvis_command("  search local LLM deployment  ") == "search local LLM deployment"


def test_empty_and_wake_only_inputs_are_safe() -> None:
    assert normalize_jarvis_command("") == ""
    assert normalize_jarvis_command("Jarvis") == ""


def test_wake_phrase_detection_requires_prefix() -> None:
    assert has_jarvis_wake_phrase("OK Jarvis, help") is True
    assert has_jarvis_wake_phrase("I was talking about Jarvis") is False
