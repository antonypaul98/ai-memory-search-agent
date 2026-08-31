from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.exceptions import AppError
from app.services.github_starred_import_service import GitHubStarredImportService
from app.services.sources import github_connector


class FakeVault:
    def __init__(self, token: str = "oauth-secret", *, expired: bool = False, connected: bool = True):
        self.token = token
        self.expired = expired
        self.connected = connected
        self.calls: list[tuple[str, str]] = []

    def get(self, *, user_id: str, connector_id: str):
        self.calls.append((user_id, connector_id))
        if not self.connected:
            return None
        return SimpleNamespace(access_token=self.token, expired=self.expired)


class FakeIngester:
    def __init__(self):
        self.calls: list[dict] = []

    def ingest_url(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return SimpleNamespace(success=True, skipped=False, error="")


def _repo(name: str, *, private: bool = False, stars: int = 1) -> dict:
    owner = name.split("/", 1)[0]
    return {
        "full_name": name,
        "html_url": f"https://github.com/{name}",
        "description": f"Description for {name}",
        "owner": {"login": owner},
        "private": private,
        "stargazers_count": stars,
        "updated_at": "2026-08-31T00:00:00Z",
        "default_branch": "main",
    }


def test_preview_is_deterministic_deduplicated_and_never_exposes_oauth_token():
    seen_tokens: list[str] = []

    def fetcher(token: str, limit: int):
        seen_tokens.append(token)
        assert limit == 100
        return [_repo("Zed/Repo"), _repo("alpha/one", private=True), _repo("zed/repo")]

    service = GitHubStarredImportService(
        vault=FakeVault(), ingester=FakeIngester(), starred_fetcher=fetcher
    )

    preview = service.preview(user_id="user-a")

    assert seen_tokens == ["oauth-secret"]
    assert preview["requires_confirmation"] is True
    assert preview["count"] == 2
    assert [item["full_name"] for item in preview["repositories"]] == ["alpha/one", "Zed/Repo"]
    assert preview["repositories"][0]["private"] is True
    assert "oauth-secret" not in repr(preview)


def test_import_refuses_to_mutate_without_explicit_confirmation():
    ingester = FakeIngester()
    service = GitHubStarredImportService(
        vault=FakeVault(), ingester=ingester, starred_fetcher=lambda _token, _limit: [_repo("a/one")]
    )

    with pytest.raises(AppError, match="Explicit confirmation"):
        service.import_starred(user_id="user-a", confirm=False)

    assert ingester.calls == []


def test_confirmed_selection_must_come_from_current_starred_preview_and_reuses_canonical_ingest():
    ingester = FakeIngester()
    service = GitHubStarredImportService(
        vault=FakeVault(),
        ingester=ingester,
        starred_fetcher=lambda _token, _limit: [_repo("b/two"), _repo("a/one", private=True)],
    )

    with pytest.raises(AppError, match="current starred-repository preview"):
        service.import_starred(
            user_id="user-a", confirm=True, selected_repositories=["not/starred"]
        )
    assert ingester.calls == []

    result = service.import_starred(
        user_id="user-a", confirm=True, selected_repositories=["B/TWO", "a/one"]
    )

    assert result["imported"] == 2
    assert result["failed"] == 0
    assert [call["url"] for call in ingester.calls] == [
        "https://github.com/a/one",
        "https://github.com/b/two",
    ]
    assert all(call["connector_id"] == "github.v1" for call in ingester.calls)
    assert all(call["user_id"] == "user-a" for call in ingester.calls)
    assert all(call["ref_extra"]["token"] == "oauth-secret" for call in ingester.calls)
    assert all("repo_json" in call["ref_extra"] for call in ingester.calls)
    assert "oauth-secret" not in repr(result)


def test_disconnected_or_expired_oauth_is_a_safe_blocker():
    disconnected = GitHubStarredImportService(
        vault=FakeVault(connected=False),
        ingester=FakeIngester(),
        starred_fetcher=lambda _token, _limit: [],
    )
    with pytest.raises(AppError, match="not connected"):
        disconnected.preview(user_id="user-a")

    expired = GitHubStarredImportService(
        vault=FakeVault(expired=True),
        ingester=FakeIngester(),
        starred_fetcher=lambda _token, _limit: [],
    )
    with pytest.raises(AppError, match="expired"):
        expired.preview(user_id="user-a")


def test_private_repository_readme_uses_ephemeral_oauth_token(monkeypatch):
    calls: list[tuple[str, str | None]] = []

    def fake_get(path: str, *, token: str | None = None):
        calls.append((path, token))
        if path.endswith("/readme"):
            import base64

            return {
                "encoding": "base64",
                "content": base64.b64encode(b"private readme evidence").decode("ascii"),
            }
        raise AssertionError(path)

    monkeypatch.setattr(github_connector, "_github_get", fake_get)
    text = github_connector._fetch_readme("owner/private", token="oauth-secret")

    assert text == "private readme evidence"
    assert calls == [("/repos/owner/private/readme", "oauth-secret")]
