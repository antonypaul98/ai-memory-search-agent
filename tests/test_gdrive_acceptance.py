from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.config import Settings
from app.core.exceptions import AppError
from app.services.gdrive_import_service import DRIVE_READONLY_SCOPE, GoogleDriveImportService
from app.services.oauth_token_vault import OAuthTokenRecord


class _Vault:
    def get(self, *, user_id: str, connector_id: str, audit_use: bool = True):
        assert user_id == "tenant-a"
        assert connector_id == "gdrive.v1"
        return OAuthTokenRecord(
            user_id=user_id,
            connector_id=connector_id,
            access_token="super-secret-access-token",
            refresh_token="super-secret-refresh-token",
            scopes=(DRIVE_READONLY_SCOPE,),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            enabled=True,
        )


def test_c04_provider_auth_failure_does_not_expose_oauth_secrets():
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(401, text="provider rejected token"))
    )
    service = GoogleDriveImportService(Settings(), vault=_Vault(), client=client)

    with pytest.raises(AppError) as exc_info:
        service.list_files(user_id="tenant-a")

    message = str(exc_info.value)
    assert message == "Google Drive authorization was rejected."
    assert "super-secret-access-token" not in message
    assert "super-secret-refresh-token" not in message
