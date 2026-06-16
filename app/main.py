"""
FastAPI application entry point.

Creates the app, registers API routes, and configures CORS for future Streamlit.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health
from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
)

# Allow Streamlit (Phase 5+) to call the API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Phase 2: health route only. Videos and search routes added in Phase 3/4.
app.include_router(health.router, prefix="/api/v1")
