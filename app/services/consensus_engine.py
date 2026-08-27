"""Deterministic cross-source agreement and contradiction analysis.

The engine intentionally operates only on evidence already retrieved for the
current user. It performs no external research and no memory writes.
"""

from __future__ import annotations

import re
from itertools import combinations

from app.models.consensus import (
    ConsensusAgreement,
    ConsensusConflict,
    ConsensusReport,
    ConsensusSide,
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?%?", re.I)
_NUMBER = re.compile(r"\b\d+(?:\.\d+)?%?\b")
_NEGATION = re.compile(r"\b(?:no|not|never|none|cannot|can't|doesn't|does not|isn't|is not|without)\b", re.I)
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "has",
    "have", "in", "is", "it", "of", "on", "or", "that", "the", "this", "to", "was",
    "were", "will", "with", "you", "your", "can", "not", "no",
}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split((text or "").strip()) if len(s.strip()) >= 12]


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(text or "") if t.lower() not in _STOPWORDS and not t[0].isdigit()}


def _similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _numbers(text: str) -> set[str]:
    return {n.lower() for n in _NUMBER.findall(text or "")}


def _source_id(hit: dict) -> str:
    return str(hit.get("video_id") or hit.get("memory_id") or hit.get("external_id") or "")


def _source_title(hit: dict) -> str:
    return str(hit.get("title") or "")


class ConsensusEngine:
    """Analyze retrieved evidence for agreement and explicit conflicts."""

    def analyze(self, evidence: list[dict]) -> ConsensusReport:
        sources: dict[str, dict] = {}
        for hit in evidence:
            sid = _source_id(hit)
            if not sid:
                continue
            record = sources.setdefault(sid, {"title": _source_title(hit), "claims": []})
            record["claims"].extend(_sentences(str(hit.get("matched_text") or "")))

        source_count = len(sources)
        if source_count < 2:
            return ConsensusReport(
                status="insufficient_sources",
                source_count=source_count,
                consensus_weight=0.0,
            )

        conflicts: list[ConsensusConflict] = []
        agreements_by_key: dict[str, dict] = {}
        source_items = list(sources.items())

        for (sid_a, src_a), (sid_b, src_b) in combinations(source_items, 2):
            for claim_a in src_a["claims"]:
                for claim_b in src_b["claims"]:
                    sim = _similarity(claim_a, claim_b)
                    if sim < 0.35:
                        continue
                    nums_a, nums_b = _numbers(claim_a), _numbers(claim_b)
                    numeric_conflict = bool(nums_a and nums_b and nums_a != nums_b)
                    negation_conflict = bool(
                        sim >= 0.45 and bool(_NEGATION.search(claim_a)) != bool(_NEGATION.search(claim_b))
                    )
                    if numeric_conflict or negation_conflict:
                        reason = "numeric_mismatch" if numeric_conflict else "negation_mismatch"
                        conflicts.append(
                            ConsensusConflict(
                                reason=reason,
                                similarity=round(sim, 4),
                                side_a=ConsensusSide(
                                    source_id=sid_a,
                                    source_title=src_a["title"],
                                    claim=claim_a,
                                ),
                                side_b=ConsensusSide(
                                    source_id=sid_b,
                                    source_title=src_b["title"],
                                    claim=claim_b,
                                ),
                            )
                        )
                        continue
                    if sim >= 0.65:
                        canonical = min(claim_a, claim_b, key=lambda x: (len(x), x.lower()))
                        key = " ".join(sorted(_tokens(canonical)))
                        entry = agreements_by_key.setdefault(
                            key,
                            {"claim": canonical, "source_ids": set(), "source_titles": set()},
                        )
                        entry["source_ids"].update((sid_a, sid_b))
                        if src_a["title"]:
                            entry["source_titles"].add(src_a["title"])
                        if src_b["title"]:
                            entry["source_titles"].add(src_b["title"])

        agreements = [
            ConsensusAgreement(
                claim=item["claim"],
                source_ids=sorted(item["source_ids"]),
                source_titles=sorted(item["source_titles"]),
                weight=round(min(1.0, len(item["source_ids"]) / source_count), 4),
            )
            for item in agreements_by_key.values()
        ]
        agreements.sort(key=lambda a: (-a.weight, a.claim.lower()))

        # Deduplicate symmetrical/repeated conflict pairs while preserving evidence text.
        deduped_conflicts: list[ConsensusConflict] = []
        seen_conflicts: set[tuple[str, str, str, str]] = set()
        for conflict in conflicts:
            pair = sorted((conflict.side_a.source_id, conflict.side_b.source_id))
            key = (pair[0], pair[1], conflict.reason, "|".join(sorted((_claim_key(conflict.side_a.claim), _claim_key(conflict.side_b.claim)))))
            if key in seen_conflicts:
                continue
            seen_conflicts.add(key)
            deduped_conflicts.append(conflict)

        if agreements and deduped_conflicts:
            status = "mixed"
        elif deduped_conflicts:
            status = "disagreement"
        elif agreements:
            status = "agreement"
        else:
            status = "inconclusive"

        consensus_weight = max((a.weight for a in agreements), default=0.0)
        if deduped_conflicts:
            consensus_weight = min(consensus_weight, 0.5)

        return ConsensusReport(
            status=status,
            source_count=source_count,
            consensus_weight=round(consensus_weight, 4),
            agreements=agreements[:10],
            conflicts=deduped_conflicts[:10],
        )

    def conflict_preserving_answer(self, report: ConsensusReport) -> str:
        """Render disagreements without collapsing them into false consensus."""
        if not report.conflicts:
            return ""
        lines = ["The saved sources disagree on part of this comparison:"]
        for conflict in report.conflicts[:5]:
            a_title = conflict.side_a.source_title or conflict.side_a.source_id
            b_title = conflict.side_b.source_title or conflict.side_b.source_id
            lines.append(f"- {a_title}: {conflict.side_a.claim}")
            lines.append(f"- {b_title}: {conflict.side_b.claim}")
        if report.agreements:
            lines.append("\nWhere the sources agree:")
            for agreement in report.agreements[:5]:
                lines.append(f"- {agreement.claim}")
        return "\n".join(lines)


def _claim_key(text: str) -> str:
    return " ".join(sorted(_tokens(text)))
