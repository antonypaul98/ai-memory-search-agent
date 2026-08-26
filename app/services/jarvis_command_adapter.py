"""Small, deterministic adapter for Jarvis-style spoken commands.

This module intentionally does not perform speech recognition. It normalizes text
produced by any future voice front end and hands the cleaned command to the
existing safe command router.
"""

from __future__ import annotations

import re

_WAKE_PREFIX = re.compile(
    r"^\s*(?:(?:hey|hi|okay|ok)\s+)?jarvis\b[\s,:;.!?-]*",
    re.IGNORECASE,
)


def normalize_jarvis_command(text: str) -> str:
    """Strip a leading Jarvis wake phrase while preserving command content.

    Examples:
        "Jarvis, search MCP servers" -> "search MCP servers"
        "Hey Jarvis tell me what I saved" -> "tell me what I saved"

    Text that does not begin with a Jarvis wake phrase is returned trimmed but
    otherwise unchanged so the existing command router remains the authority on
    intent classification and safety policy.
    """
    raw = (text or "").strip()
    if not raw:
        return ""
    return _WAKE_PREFIX.sub("", raw, count=1).strip()


def has_jarvis_wake_phrase(text: str) -> bool:
    """Return True only when the utterance begins with the Jarvis wake phrase."""
    return bool(_WAKE_PREFIX.match(text or ""))
