"""
FastAPI application entry point.

Creates the app, registers API routes, and configures CORS for future Streamlit.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.routes import agent, agents, auth, cache, capture, chat, connector_auth, context, events, feedback, gdrive, health, imports, intelligence, jobs, knowledge, memories, models, playlists, podcasts, privacy, search, usage, videos, youtube
from app.config import get_settings
from app.db.schema import migrate
from app.middleware.observability import ObservabilityMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.services.job_worker import start_job_worker, stop_job_worker

logger = logging.getLogger(__name__)
settings = get_settings()
STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime_settings = get_settings()
    migrate(runtime_settings)
    if runtime_settings.jobs_enabled:
        start_job_worker(runtime_settings)
    yield
    stop_job_worker()


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)

_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
_origins = [o for o in _origins if o != "chrome-extension://" and not o.endswith("chrome-extension://")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_origin_regex=r"chrome-extension://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(ObservabilityMiddleware)

app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(privacy.router, prefix="/api/v1")
app.include_router(agent.router, prefix="/api/v1")
app.include_router(agents.router, prefix="/api/v1")
app.include_router(videos.router, prefix="/api/v1")
app.include_router(youtube.router, prefix="/api/v1")
app.include_router(intelligence.router, prefix="/api/v1")
app.include_router(playlists.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(capture.router, prefix="/api/v1")
app.include_router(imports.router, prefix="/api/v1")
app.include_router(podcasts.router, prefix="/api/v1")
app.include_router(gdrive.router, prefix="/api/v1")
app.include_router(connector_auth.router, prefix="/api/v1")
app.include_router(usage.router, prefix="/api/v1")
app.include_router(search.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(memories.router, prefix="/api/v1")
app.include_router(knowledge.router, prefix="/api/v1")
app.include_router(cache.router, prefix="/api/v1")
app.include_router(events.router, prefix="/api/v1")
app.include_router(context.router, prefix="/api/v1")
app.include_router(models.router, prefix="/api/v1")
app.include_router(feedback.router, prefix="/api/v1")


@app.get("/")
async def serve_demo_ui() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/privacy")
async def privacy_policy_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "privacy.html")


@app.get("/share")
async def share_target_entry(url: str = "", text: str = "", title: str = "") -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/manifest.webmanifest")
async def pwa_manifest() -> FileResponse:
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
async def service_worker() -> Response:
    content = (STATIC_DIR / "sw.js").read_text(encoding="utf-8")
    return Response(content, media_type="application/javascript")


@app.get("/api/v1/pwa/config")
async def pwa_config() -> JSONResponse:
    return JSONResponse(
        {
            "pwa_enabled": settings.pwa_enabled,
            "auth_enabled": settings.auth_enabled,
            "jobs_enabled": settings.jobs_enabled,
            "privacy_policy_url": "/privacy",
            "rate_limit_enabled": settings.rate_limit_enabled,
        }
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
