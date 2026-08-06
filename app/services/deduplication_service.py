"""Content hashing and near-duplicate detection."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


@dataclass
class DedupReport:
    duplicate_urls_removed: int = 0
    exact_duplicate_chunks_removed: int = 0
    near_duplicate_chunks_suppressed: int = 0
    embeddings_avoided: int = 0
    estimated_bytes_saved: int = 0


def hash_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def simhash64(text: str) -> int:
    tokens = re.findall(r"[a-z0-9]{3,}", text.lower())
    if not tokens:
        return 0
    vector = [0] * 64
    for token in tokens:
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        for i in range(64):
            vector[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i, bit in enumerate(vector):
        if bit >= 0:
            out |= 1 << i
    return out


def hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def is_near_duplicate(a: int, b: int, threshold: int = 3) -> bool:
    return hamming_distance(a, b) <= threshold


def dedupe_chunk_texts(texts: list[str]) -> tuple[list[str], DedupReport]:
    report = DedupReport()
    kept: list[str] = []
    seen_hashes: set[str] = set()
    seen_simhashes: list[int] = []

    for text in texts:
        content_hash = hash_text(text)
        if content_hash in seen_hashes:
            report.exact_duplicate_chunks_removed += 1
            report.embeddings_avoided += 1
            report.estimated_bytes_saved += len(text.encode("utf-8"))
            continue
        sh = simhash64(text)
        if any(is_near_duplicate(sh, existing) for existing in seen_simhashes):
            report.near_duplicate_chunks_suppressed += 1
            report.embeddings_avoided += 1
            report.estimated_bytes_saved += len(text.encode("utf-8"))
            continue
        seen_hashes.add(content_hash)
        seen_simhashes.append(sh)
        kept.append(text)
    return kept, report
