"""Confirmation-gated GitHub starred-repository import.

V1-08 reuses the tenant-scoped OAuth vault and the canonical ``github.v1``
connector ingest path. OAuth credentials never leave this service and are never
returned in preview/import responses.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.core.exceptions import AppError
from app.services.connector_ingest_service import ConnectorIngestService
from app.services.oauth_token_vault import OAuthTokenVault
from app.services.sources.github_connector import _github_headers

GITHUB_CONNECTOR_ID = "github.v1"
StarredFetcher = Callable[[str, int], list[dict[str, Any]]]


class GitHubStarredImportService:
    """Preview and explicitly import the authenticated user's GitHub stars."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        vault: OAuthTokenVault | None = None,
        ingester: ConnectorIngestService | None = None,
        starred_fetcher: StarredFetcher | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._vault = vault or OAuthTokenVault(self._settings)
        self._ingester = ingester or ConnectorIngestService(self._settings)
        self._fetcher = starred_fetcher or _fetch_starred_repositories

    def preview(self, *, user_id: str, limit: int = 100) -> dict[str, object]:
        token = self._access_token(user_id)
        repos = self._canonical_candidates(self._fetcher(token, limit))
        return {
            "connector_id": GITHUB_CONNECTOR_ID,
            "count": len(repos),
            "repositories": [self._public_repo_view(repo) for repo in repos],
            "requires_confirmation": True,
        }

    def import_starred(
        self,
        *,
        user_id: str,
        confirm: bool,
        selected_repositories: list[str] | None = None,
        force_refresh: bool = False,
        limit: int = 500,
    ) -> dict[str, object]:
        if not confirm:
            raise AppError("Explicit confirmation is required before importing GitHub stars.")

        token = self._access_token(user_id)
        repos = self._canonical_candidates(self._fetcher(token, limit))
        by_name = {str(repo["full_name"]).casefold(): repo for repo in repos}

        if selected_repositories:
            wanted = sorted({name.strip().casefold() for name in selected_repositories if name.strip()})
            unknown = [name for name in wanted if name not in by_name]
            if unknown:
                raise AppError("Selected repositories must come from the current starred-repository preview.")
            repos = [by_name[name] for name in wanted]

        imported = 0
        skipped = 0
        failed = 0
        results: list[dict[str, object]] = []
        for repo in repos:
            full_name = str(repo["full_name"])
            url = f"https://github.com/{full_name}"
            result = self._ingester.ingest_url(
                url,
                user_id=user_id,
                force_refresh=force_refresh,
                connector_id=GITHUB_CONNECTOR_ID,
                ref_extra={"repo_json": repo, "token": token},
            )
            if result.success and result.skipped:
                skipped += 1
            elif result.success:
                imported += 1
            else:
                failed += 1
            results.append(
                {
                    "repository": full_name,
                    "success": bool(result.success),
                    "skipped": bool(result.skipped),
                    "error": result.error or "",
                }
            )

        return {
            "connector_id": GITHUB_CONNECTOR_ID,
            "imported": imported,
            "skipped": skipped,
            "failed": failed,
            "total": len(repos),
            "results": results,
        }

    def _access_token(self, user_id: str) -> str:
        record = self._vault.get(user_id=user_id, connector_id=GITHUB_CONNECTOR_ID)
        if record is None:
            raise AppError("GitHub is not connected. Complete GitHub OAuth before importing starred repositories.")
        if record.expired:
            raise AppError("GitHub OAuth token is expired. Reconnect GitHub before importing starred repositories.")
        token = record.access_token.strip()
        if not token:
            raise AppError("GitHub OAuth token is unavailable. Reconnect GitHub.")
        return token

    @staticmethod
    def _canonical_candidates(repos: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_name: dict[str, dict[str, Any]] = {}
        for repo in repos:
            full_name = str(repo.get("full_name") or "").strip()
            if "/" not in full_name or full_name.startswith("/") or full_name.endswith("/"):
                continue
            by_name.setdefault(full_name.casefold(), repo)
        return [by_name[key] for key in sorted(by_name)]

    @staticmethod
    def _public_repo_view(repo: dict[str, Any]) -> dict[str, object]:
        owner = repo.get("owner") or {}
        return {
            "full_name": str(repo.get("full_name") or ""),
            "url": str(repo.get("html_url") or ""),
            "description": str(repo.get("description") or "")[:500],
            "owner": str(owner.get("login") or ""),
            "private": bool(repo.get("private")),
            "stars": int(repo.get("stargazers_count") or 0),
            "updated_at": str(repo.get("updated_at") or ""),
        }


def _fetch_starred_repositories(access_token: str, limit: int) -> list[dict[str, Any]]:
    """Fetch up to ``limit`` starred repos using GitHub's authenticated REST API."""
    if limit < 1 or limit > 1000:
        raise AppError("GitHub starred import limit must be between 1 and 1000.")
    repos: list[dict[str, Any]] = []
    page = 1
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        while len(repos) < limit:
            per_page = min(100, limit - len(repos))
            response = client.get(
                "https://api.github.com/user/starred",
                params={"per_page": per_page, "page": page},
                headers=_github_headers(access_token),
            )
            if response.status_code == 401:
                raise AppError("GitHub authorization was rejected. Reconnect GitHub.")
            if response.status_code == 403:
                raise AppError("GitHub API rate limit or authorization policy blocked starred import.")
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise AppError("GitHub starred-repository response was invalid.")
            batch = [item for item in payload if isinstance(item, dict)]
            repos.extend(batch)
            if len(batch) < per_page:
                break
            page += 1
    return repos[:limit]
