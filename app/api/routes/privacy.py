"""Privacy export / delete-all APIs (V1-8 + portable Markdown export)."""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response

from app.api.auth import get_current_user
from app.config import Settings, get_settings
from app.models.user import UserPublic
from app.services.privacy_service import PrivacyService, dump_export_json, dump_export_markdown

router = APIRouter(prefix="/privacy", tags=["privacy"])

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def _privacy(settings: Settings = Depends(get_settings)) -> PrivacyService:
    return PrivacyService(settings)


def _export_filename(user_id: str, extension: str = "json") -> str:
    safe = _SAFE_FILENAME.sub("_", (user_id or "user").strip())[:80] or "user"
    suffix = "md" if extension == "markdown" else "json"
    return f"ai-memory-export-{safe}.{suffix}"


@router.get("/export")
def export_my_data(
    user: UserPublic = Depends(get_current_user),
    privacy: PrivacyService = Depends(_privacy),
    download: bool = False,
    export_format: Literal["json", "markdown"] = Query("json", alias="format"),
) -> Response:
    payload = privacy.export_user_data(user_id=user.user_id)

    if export_format == "markdown":
        headers = {}
        if download:
            headers["Content-Disposition"] = (
                f'attachment; filename="{_export_filename(user.user_id, "markdown")}"'
            )
        return Response(
            content=dump_export_markdown(payload),
            media_type="text/markdown; charset=utf-8",
            headers=headers,
        )

    if download:
        body = dump_export_json(payload)
        return Response(
            content=body,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{_export_filename(user.user_id)}"'
            },
        )
    return JSONResponse(payload)


@router.delete("/memories")
def delete_all_my_memories(
    user: UserPublic = Depends(get_current_user),
    privacy: PrivacyService = Depends(_privacy),
) -> dict:
    return privacy.delete_all_memories(user_id=user.user_id)
