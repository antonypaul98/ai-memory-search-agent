"""
Custom application exceptions.

Each exception maps to an HTTP status code in the API layer.
Services raise these; routes translate them into JSON error responses.
"""


class AppError(Exception):
    """Base exception for all application errors."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class InvalidYouTubeURLError(AppError):
    """Raised when a URL is not a valid YouTube link or has no video ID."""


class TranscriptUnavailableError(AppError):
    """Raised when a video has no captions or transcripts are disabled."""


class TranscriptFetchError(AppError):
    """Raised when transcript fetching fails due to network or API errors."""


class ChromaConnectionError(AppError):
    """Raised when ChromaDB cannot be reached or the collection is inaccessible."""


class MetadataFetchError(AppError):
    """Raised when platform metadata cannot be fetched."""
