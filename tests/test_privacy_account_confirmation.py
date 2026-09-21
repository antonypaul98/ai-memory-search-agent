"""No account fence or deletion may precede exact authenticated confirmation."""
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.routes.privacy import AccountErasureRequest, erase_my_account
from app.models.user import UserPublic
from app.services import privacy_erasure


def test_confirmation_mismatch_does_not_start_erasure(monkeypatch):
    erase = Mock()
    monkeypatch.setattr(privacy_erasure, "delete_production_user_data", erase)
    with pytest.raises(ValueError, match="confirmation"):
        privacy_erasure.erase_confirmed_account(object(), user_id="target", confirm_user_id="neighbor")
    erase.assert_not_called()
    with pytest.raises(HTTPException) as exc:
        erase_my_account(AccountErasureRequest(confirm_user_id="neighbor"), user=UserPublic(user_id="target"),
                         settings=object(), capture_registry=None)
    assert exc.value.status_code == 409
    erase.assert_not_called()


def test_confirmed_route_uses_authenticated_owner(monkeypatch):
    from app.db import production_storage_profile
    monkeypatch.setattr(production_storage_profile, "is_complete_postgres_profile", lambda settings: True)
    erase = Mock(return_value={"deleted": True})
    monkeypatch.setattr(privacy_erasure, "erase_confirmed_account", erase)
    settings, registry = object(), object()
    assert erase_my_account(AccountErasureRequest(confirm_user_id="target"), user=UserPublic(user_id="target"),
                            settings=settings, capture_registry=registry) == {"deleted": True}
    erase.assert_called_once_with(settings, user_id="target", confirm_user_id="target", capture_registry=registry)


def test_legacy_backfill_cannot_assign_production_ownership(monkeypatch):
    from app.config import Settings
    from app.db.production_storage_profile import RELATIONAL_STORE_BACKEND_FIELDS
    from app.services import legacy_user_backfill
    read = Mock(side_effect=AssertionError("must reject before vector access"))
    monkeypatch.setattr(legacy_user_backfill, "get_collection", read)
    settings = Settings(_env_file=None, **{field: "postgres" for field in RELATIONAL_STORE_BACKEND_FIELDS})
    with pytest.raises(PermissionError, match="must not be guessed"):
        legacy_user_backfill.backfill_legacy_user_ids(settings)
    read.assert_not_called()
