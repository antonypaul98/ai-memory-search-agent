"""GitHub repository connector — public repo metadata + README."""

from __future__ import annotations

import re

from app.core.exceptions import AppError, MetadataFetchError, TranscriptUnavailableError
from app.models.video import SourceType
from app.services.deduplication_service import hash_text
from app.services.sources.base_source import (
    ConnectorHealth,
    NormalizedItem,
    SourceConnector,
    SourceRef,
    TextSegment,
    TranscriptAvailability,
    TranscriptKind,
    TranscriptPayload,
)
from app.services.ssrf_fetch import validate_public_http_url

CONNECTOR_ID = "github.v1"
_REPO_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)(?:/|$)",
    re.I,
)


class GitHubConnector(SourceConnector):
    source_type = SourceType.GITHUB
    connector_id = CONNECTOR_ID

    def health(self) -> ConnectorHealth:
        try:
            import httpx  # noqa: F401

            return ConnectorHealth(connector_id=self.connector_id, healthy=True, detail="ok")
        except Exception as exc:
            return ConnectorHealth(connector_id=self.connector_id, healthy=False, detail=str(exc))

    def parse_ref(self, url: str) -> SourceRef:
        safe = validate_public_http_url(url.strip(), resolve_dns=False)
        match = _REPO_RE.match(safe.rstrip("/"))
        if not match:
            raise AppError("Not a GitHub repository URL.")
        owner = match.group("owner")
        repo = match.group("repo").removesuffix(".git")
        canonical = f"https://github.com/{owner}/{repo}"
        return SourceRef(
            url=canonical,
            external_id=f"{owner}/{repo}",
            extra={"owner": owner, "repo": repo},
        )

    def supports_url(self, url: str) -> bool:
        try:
            self.parse_ref(url)
            return True
        except Exception:
            return False

    def fetch_metadata(self, ref: SourceRef) -> NormalizedItem:
        if not ref.external_id:
            ref = self.parse_ref(ref.url)
        data = ref.extra.get("repo_json") or _github_get(f"/repos/{ref.external_id}", token=ref.extra.get("token"))
        title = data.get("full_name") or ref.external_id
        description = data.get("description") or ""
        topics = data.get("topics") or []
        content_hash = hash_text(f"{title}\n{description}\n{','.join(topics)}")
        return NormalizedItem(
            source_type=self.source_type,
            connector_id=self.connector_id,
            external_id=ref.external_id,
            canonical_url=data.get("html_url") or ref.url,
            title=str(title)[:500],
            author=str((data.get("owner") or {}).get("login") or ref.extra.get("owner") or ""),
            published_at=data.get("created_at"),
            language=data.get("language"),
            description=description[:5000],
            tags=list(topics)[:40],
            content_hash=content_hash,
            raw_metadata={
                "stars": data.get("stargazers_count") or 0,
                "license": ((data.get("license") or {}) or {}).get("spdx_id") or "",
                "default_branch": data.get("default_branch") or "main",
                "updated_at": data.get("updated_at") or "",
                "topics": topics,
                "private": bool(data.get("private")),
            },
        )

    def detect_transcript(self, ref: SourceRef) -> TranscriptAvailability:
        try:
            payload = self.fetch_transcript(ref)
            return payload.availability
        except TranscriptUnavailableError:
            return TranscriptAvailability.UNAVAILABLE
        except Exception:
            return TranscriptAvailability.UNKNOWN

    def fetch_transcript(self, ref: SourceRef) -> TranscriptPayload:
        if not ref.external_id:
            ref = self.parse_ref(ref.url)
        meta = self.fetch_metadata(ref)
        token = str(ref.extra.get("token") or "")
        if meta.raw_metadata.get("private") and not token:
            raise TranscriptUnavailableError("Private repository requires authorization.")
        readme = ref.extra.get("readme_text")
        if readme is None:
            readme = _fetch_readme(
                ref.external_id,
                branch=str(meta.raw_metadata.get("default_branch") or "main"),
                token=token or None,
            )
        parts = [meta.description or "", readme or ""]
        text = "\n\n".join(p for p in parts if p).strip()
        if not text:
            raise TranscriptUnavailableError("No README or description available.")
        segments = [
            TextSegment(text=p, start_time_sec=float(i), duration_sec=0.0)
            for i, p in enumerate([p for p in parts if p])
        ]
        return TranscriptPayload(
            external_id=ref.external_id,
            segments=segments,
            full_text=text,
            language=meta.language,
            kind=TranscriptKind.MANUAL,
            availability=TranscriptAvailability.AVAILABLE,
        )


def _github_headers(token: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "AI-Memory-Search-Agent",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _github_get(path: str, *, token: str | None = None) -> dict:
    import httpx

    url = f"https://api.github.com{path}"
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        resp = client.get(url, headers=_github_headers(token))
        if resp.status_code == 404:
            raise MetadataFetchError(f"GitHub resource not found: {path}")
        if resp.status_code == 401:
            raise MetadataFetchError("GitHub authorization required.")
        if resp.status_code == 403:
            raise MetadataFetchError("GitHub API rate limited or forbidden.")
        resp.raise_for_status()
        return resp.json()


def _fetch_readme(full_name: str, *, branch: str = "main", token: str | None = None) -> str:
    import base64

    import httpx

    # Prefer Contents API; authenticated calls support explicitly confirmed private repos.
    try:
        data = _github_get(f"/repos/{full_name}/readme", token=token)
        if data.get("encoding") == "base64" and data.get("content"):
            return base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
        if data.get("download_url"):
            with httpx.Client(timeout=20.0, follow_redirects=True) as client:
                resp = client.get(data["download_url"], headers=_github_headers(token))
                resp.raise_for_status()
                return resp.text
    except Exception:
        pass
    # Fallback raw (public repos; private repos normally resolve through Contents API above).
    for name in ("README.md", "Readme.md", "README.rst", "README"):
        raw_url = f"https://raw.githubusercontent.com/{full_name}/{branch}/{name}"
        try:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                resp = client.get(raw_url, headers=_github_headers(token))
                if resp.status_code == 200 and resp.text.strip():
                    return resp.text
        except Exception:
            continue
    return ""
