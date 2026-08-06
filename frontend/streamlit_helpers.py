"""
HTTP helpers for the Streamlit frontend.

Separated from streamlit_app.py for lightweight unit testing.
"""

from __future__ import annotations

import httpx


def parse_ingest_response(data: object) -> dict:
    """Validate and normalize a POST /api/v1/videos/ingest JSON body."""
    if not isinstance(data, dict):
        raise ValueError("Ingest response must be a JSON object.")

    results = data.get("results")
    if not isinstance(results, list):
        raise ValueError("Ingest response missing 'results' list.")

    return {
        "total": int(data.get("total", len(results))),
        "succeeded": int(data.get("succeeded", 0)),
        "failed": int(data.get("failed", 0)),
        "results": results,
    }


def format_http_error(exc: Exception) -> str:
    """Build a readable API error message for the UI."""
    if isinstance(exc, httpx.TimeoutException):
        return (
            "API request timed out. Ingest can take several minutes on the first run "
            "while metadata, transcripts, and embeddings are processed."
        )

    if isinstance(exc, httpx.HTTPStatusError):
        detail = exc.response.text.strip()
        if detail:
            return f"API request failed ({exc.response.status_code}): {detail}"
        return f"API request failed with status {exc.response.status_code}."

    if isinstance(exc, httpx.HTTPError):
        return f"API request failed: {exc}"

    if isinstance(exc, ValueError):
        return f"Could not parse API response: {exc}"

    return f"Unexpected error: {exc}"
