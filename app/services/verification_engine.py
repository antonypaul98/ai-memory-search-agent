"""Deterministic claim-level verification against retrieved evidence."""

from __future__ import annotations

import re

from app.models.verification import VerificationClaim, VerificationReport

_STOPWORDS = {
    "about", "after", "again", "also", "because", "before", "being", "between",
    "could", "does", "from", "have", "into", "more", "most", "other", "over",
    "should", "than", "that", "their", "there", "these", "they", "this", "those",
    "through", "under", "using", "very", "what", "when", "where", "which", "while",
    "with", "would", "your",
}
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_+.-]*", re.IGNORECASE)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")


class VerificationEngine:
    """Map answer claims to evidence or explicitly flag them.

    This deliberately uses deterministic lexical/number agreement rather than an
    LLM so verification remains available when providers are disabled or fail.
    """

    def verify(self, answer: str, evidence: list[dict]) -> VerificationReport:
        claims = [_clean_claim(part) for part in _SENTENCE_RE.split(answer or "")]
        claims = [claim for claim in claims if claim]
        if not claims:
            return VerificationReport(score=0.0, claims=[])

        prepared = []
        for item in evidence:
            text = str(item.get("matched_text") or "").strip()
            if not text:
                continue
            evidence_id = str(item.get("evidence_id") or _evidence_id(item))
            prepared.append((evidence_id, _tokens(text), _numbers(text)))

        verified: list[VerificationClaim] = []
        for claim in claims:
            claim_tokens = _tokens(claim)
            claim_numbers = _numbers(claim)
            scored: list[tuple[float, str]] = []
            for evidence_id, evidence_tokens, evidence_numbers in prepared:
                score = _support_score(
                    claim_tokens,
                    evidence_tokens,
                    claim_numbers,
                    evidence_numbers,
                )
                scored.append((score, evidence_id))

            scored.sort(reverse=True)
            best_score = scored[0][0] if scored else 0.0
            if best_score >= 0.34:
                status = "supported"
                ids = [evidence_id for score, evidence_id in scored[:3] if score >= 0.24]
            elif best_score >= 0.14:
                status = "uncertain"
                ids = [scored[0][1]] if scored else []
            else:
                status = "unsupported"
                ids = []

            verified.append(
                VerificationClaim(
                    claim=claim,
                    status=status,
                    evidence_ids=ids,
                    score=round(best_score, 4),
                )
            )

        supported = sum(1 for item in verified if item.status == "supported")
        uncertain = sum(1 for item in verified if item.status == "uncertain")
        unsupported = sum(1 for item in verified if item.status == "unsupported")
        aggregate = (supported + 0.5 * uncertain) / len(verified)
        return VerificationReport(
            score=round(aggregate, 4),
            claims=verified,
            supported_count=supported,
            uncertain_count=uncertain,
            unsupported_count=unsupported,
        )


def _clean_claim(value: str) -> str:
    value = re.sub(r"^\s*(?:[-*•]+|\d+[.)])\s*", "", value or "").strip()
    return value


def _tokens(value: str) -> set[str]:
    return {
        token.lower().strip("._+-")
        for token in _TOKEN_RE.findall(value or "")
        if len(token.strip("._+-")) >= 3
        and token.lower().strip("._+-") not in _STOPWORDS
    }


def _numbers(value: str) -> set[str]:
    return set(re.findall(r"\b\d+(?:\.\d+)?%?\b", value or ""))


def _support_score(
    claim_tokens: set[str],
    evidence_tokens: set[str],
    claim_numbers: set[str],
    evidence_numbers: set[str],
) -> float:
    if not claim_tokens or not evidence_tokens:
        return 0.0
    overlap = len(claim_tokens & evidence_tokens)
    lexical = overlap / max(1, len(claim_tokens))
    # A factual number absent from the evidence is a strong warning rather than
    # something lexical overlap should hide.
    if claim_numbers and not claim_numbers.issubset(evidence_numbers):
        lexical *= 0.35
    return min(1.0, lexical)


def _evidence_id(item: dict) -> str:
    video_id = str(item.get("video_id") or "unknown")
    start = item.get("start_time")
    if start is not None:
        return f"{video_id}@{int(start)}"
    return str(item.get("doc_id") or video_id)
