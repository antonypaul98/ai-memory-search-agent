"""Safe RSS/Atom podcast discovery and import."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

import httpx

from app.config import Settings
from app.core.exceptions import AppError
from app.services.connector_ingest_service import ConnectorIngestService
from app.services.ssrf_fetch import validate_public_http_url

_MAX_FEED_BYTES = 5 * 1024 * 1024
_MAX_REDIRECTS = 5


@dataclass(frozen=True)
class PodcastEpisode:
    external_id: str
    title: str
    show: str
    episode_url: str
    guid: str
    published_at: str
    description: str
    duration: str
    audio_url: str
    transcript_url: str

    def as_dict(self) -> dict:
        return {
            "external_id": self.external_id,
            "title": self.title,
            "show": self.show,
            "episode_url": self.episode_url,
            "guid": self.guid,
            "published_at": self.published_at,
            "description": self.description,
            "duration": self.duration,
            "audio_url": self.audio_url,
            "transcript_url": self.transcript_url,
        }


class PodcastImportService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def preview(self, feed_url: str, *, limit: int = 25, xml_text: str | None = None) -> dict:
        if limit < 1 or limit > 100:
            raise AppError("Podcast preview limit must be between 1 and 100.")
        safe_url = validate_public_http_url(feed_url, resolve_dns=xml_text is None)
        xml = xml_text if xml_text is not None else self._fetch_feed(safe_url)
        show, episodes = _parse_feed(xml, safe_url)
        selected = episodes[:limit]
        return {
            "feed_url": safe_url,
            "show": show,
            "total_discovered": len(episodes),
            "episodes": [episode.as_dict() for episode in selected],
        }

    def ingest(
        self,
        feed_url: str,
        *,
        user_id: str,
        limit: int = 25,
        force_refresh: bool = False,
        xml_text: str | None = None,
    ) -> dict:
        preview = self.preview(feed_url, limit=limit, xml_text=xml_text)
        service = ConnectorIngestService(self._settings)
        results = []
        for episode in preview["episodes"]:
            ref_url = f"podcast://episode/{episode['external_id']}"
            extra = dict(episode)
            extra["feed_url"] = preview["feed_url"]
            result = service.ingest_url(
                ref_url,
                user_id=user_id,
                force_refresh=force_refresh,
                connector_id="podcast.v1",
                ref_extra=extra,
            )
            results.append({
                "external_id": result.video_id or episode["external_id"],
                "title": result.title or episode["title"],
                "success": result.success,
                "skipped": result.skipped,
                "chunk_count": result.chunk_count,
                "error": result.error,
            })
        return {
            "feed_url": preview["feed_url"],
            "show": preview["show"],
            "total": len(results),
            "succeeded": sum(1 for item in results if item["success"]),
            "failed": sum(1 for item in results if not item["success"]),
            "skipped": sum(1 for item in results if item["skipped"]),
            "results": results,
        }

    def _fetch_feed(self, url: str) -> str:
        current = validate_public_http_url(url)
        timeout = self._settings.capture_fetch_timeout_sec
        max_bytes = min(_MAX_FEED_BYTES, self._settings.capture_max_response_bytes)
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                with client.stream("GET", current) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise AppError("Podcast feed redirect is missing Location header.")
                        current = validate_public_http_url(urljoin(current, location))
                        continue
                    response.raise_for_status()
                    ctype = (response.headers.get("content-type") or "").lower()
                    if ctype and not any(token in ctype for token in ("xml", "rss", "atom", "text/plain", "octet-stream")):
                        raise AppError("Podcast feed returned an unsupported content type.")
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise AppError("Podcast feed is too large.")
                        chunks.append(chunk)
                    return b"".join(chunks).decode("utf-8", errors="replace")
        raise AppError("Podcast feed redirected too many times.")


def _parse_feed(xml: str, feed_url: str) -> tuple[str, list[PodcastEpisode]]:
    if not xml.strip():
        raise AppError("Podcast feed is empty.")
    lowered = xml[:4096].lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise AppError("Podcast feed contains unsupported XML declarations.")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise AppError("Invalid podcast RSS/Atom XML.") from exc

    channel = _first_child(root, "channel")
    parent = channel or root
    show = _text(parent, "title") or "Podcast"
    item_nodes = _children(parent, "item")
    if not item_nodes:
        item_nodes = _children(parent, "entry")

    episodes: list[PodcastEpisode] = []
    seen: set[str] = set()
    for node in item_nodes:
        title = _text(node, "title") or "Podcast episode"
        guid = _text(node, "guid") or _text(node, "id")
        episode_url = _link(node)
        description = _text(node, "encoded") or _text(node, "description") or _text(node, "summary") or _text(node, "content")
        published = _text(node, "pubDate") or _text(node, "published") or _text(node, "updated")
        duration = _text(node, "duration")
        audio_url = ""
        transcript_url = ""
        for child in list(node):
            lname = _local(child.tag)
            if lname == "enclosure" and not audio_url:
                audio_url = str(child.attrib.get("url") or "").strip()
            elif lname == "transcript" and not transcript_url:
                transcript_url = str(child.attrib.get("url") or "").strip()
        identity = guid or episode_url or audio_url or f"{feed_url}|{title}|{published}"
        external_id = sha256(identity.encode("utf-8")).hexdigest()[:24]
        if external_id in seen:
            continue
        seen.add(external_id)
        episodes.append(PodcastEpisode(
            external_id=external_id,
            title=title,
            show=show,
            episode_url=episode_url,
            guid=guid,
            published_at=published,
            description=description,
            duration=duration,
            audio_url=audio_url,
            transcript_url=transcript_url,
        ))
    if not episodes:
        raise AppError("Podcast feed contains no episodes.")
    return show, episodes


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].split(":")[-1]


def _children(node: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in list(node) if _local(child.tag) == name]


def _first_child(node: ET.Element, name: str) -> ET.Element | None:
    for child in list(node):
        if _local(child.tag) == name:
            return child
    return None


def _text(node: ET.Element, name: str) -> str:
    for child in list(node):
        if _local(child.tag) == name:
            return "".join(child.itertext()).strip()
    return ""


def _link(node: ET.Element) -> str:
    for child in list(node):
        if _local(child.tag) != "link":
            continue
        href = str(child.attrib.get("href") or "").strip()
        rel = str(child.attrib.get("rel") or "alternate").lower()
        if href and rel in {"alternate", ""}:
            return href
        text = "".join(child.itertext()).strip()
        if text:
            return text
    return ""
