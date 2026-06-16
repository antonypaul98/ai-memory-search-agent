"""Response schemas for the health check endpoint."""

from pydantic import BaseModel, Field


class ChromaHealthDetail(BaseModel):
    """ChromaDB connection details returned by the health check."""

    connected: bool = Field(description="Whether ChromaDB responded successfully.")
    collection: str = Field(description="Name of the active Chroma collection.")
    persist_dir: str = Field(description="Filesystem path for Chroma persistent storage.")
    document_count: int = Field(description="Number of chunk documents in the collection.")


class HealthResponse(BaseModel):
    """Overall application health status."""

    status: str = Field(description='Always "ok" when the API and Chroma are healthy.')
    app_name: str = Field(description="Application name from settings.")
    chroma: ChromaHealthDetail = Field(description="ChromaDB health details.")
