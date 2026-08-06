"""Maximum Marginal Relevance evidence selection."""

from __future__ import annotations


def _token_set(text: str) -> set[str]:
    return {t for t in text.lower().split() if len(t) >= 3}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def mmr_select(
    candidates: list[dict],
    *,
    limit: int,
    lambda_: float = 0.7,
    text_key: str = "matched_text",
    score_key: str = "relevance_score",
) -> list[dict]:
    if not candidates:
        return []
    selected: list[dict] = []
    remaining = list(candidates)
    token_cache = {id(c): _token_set(c.get(text_key, "")) for c in remaining}

    while remaining and len(selected) < limit:
        best_idx = 0
        best_score = float("-inf")
        for idx, candidate in enumerate(remaining):
            relevance = float(candidate.get(score_key, 0.0))
            if not selected:
                mmr = relevance
            else:
                max_sim = max(
                    _jaccard(token_cache[id(candidate)], token_cache[id(s)])
                    for s in selected
                )
                mmr = lambda_ * relevance - (1 - lambda_) * max_sim
            if mmr > best_score:
                best_score = mmr
                best_idx = idx
        selected.append(remaining.pop(best_idx))
    return selected
