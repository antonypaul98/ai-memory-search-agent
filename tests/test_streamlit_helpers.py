"""Tests for Streamlit ingest helper functions."""

import pytest

from frontend.streamlit_helpers import format_http_error, parse_ingest_response


class TestParseIngestResponse:
    def test_parses_valid_response(self) -> None:
        data = parse_ingest_response(
            {
                "total": 2,
                "succeeded": 1,
                "failed": 1,
                "results": [
                    {"url": "https://youtu.be/a", "success": True},
                    {"url": "https://youtu.be/b", "success": False, "error": "bad"},
                ],
            }
        )
        assert data["total"] == 2
        assert data["succeeded"] == 1
        assert data["failed"] == 1
        assert len(data["results"]) == 2

    def test_rejects_non_object(self) -> None:
        with pytest.raises(ValueError, match="JSON object"):
            parse_ingest_response(["not", "a", "dict"])


class TestFormatHttpError:
    def test_formats_value_error(self) -> None:
        message = format_http_error(ValueError("bad json"))
        assert "Could not parse API response" in message
