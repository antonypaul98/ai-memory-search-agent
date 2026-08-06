"""SSRF-safe HTTP fetch for article capture."""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

import httpx

from app.core.exceptions import AppError

_BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}


def validate_public_http_url(url: str, *, resolve_dns: bool = True) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise AppError("Only http and https URLs are allowed.")
    host = (parsed.hostname or "").lower()
    if not host or host in _BLOCKED_HOSTS or host.endswith(".local"):
        raise AppError("Blocked host.")
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            raise AppError("Private network addresses are not allowed.")
    except ValueError:
        if resolve_dns:
            _reject_private_ip(host)
    return url.strip()


def fetch_readable_text(url: str, *, timeout: int, max_bytes: int) -> str:
    safe_url = validate_public_http_url(url)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        with client.stream("GET", safe_url) as resp:
            resp.raise_for_status()
            ctype = resp.headers.get("content-type", "")
            if "text/html" not in ctype and "text/plain" not in ctype:
                raise AppError("Unsupported content type for capture.")
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise AppError("Response too large.")
                chunks.append(chunk)
    html = b"".join(chunks).decode("utf-8", errors="ignore")
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:20000]


def _reject_private_ip(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise AppError("Could not resolve host.") from exc
    for info in infos:
        ip = info[4][0]
        addr = ipaddress.ip_address(ip)
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            raise AppError("Private network addresses are not allowed.")
