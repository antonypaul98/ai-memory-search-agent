"""N-01 Consensus Engine acceptance regression.

Locks the user-visible contract: comparison evidence preserves contradictory
claims and the Ask workspace exposes the consensus weight/source count instead
of silently collapsing disagreements.
"""

from pathlib import Path

from app.services.consensus_engine import ConsensusEngine


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def _hit(source_id: str, title: str, text: str) -> dict:
    return {
        "video_id": source_id,
        "title": title,
        "matched_text": text,
        "relevance_score": 0.9,
    }


def test_comparison_preserves_both_conflicting_sources_with_weight() -> None:
    engine = ConsensusEngine()
    report = engine.analyze(
        [
            _hit("source-a", "Battery Test A", "The battery lasts 10 hours under normal daily use."),
            _hit("source-b", "Battery Test B", "The battery lasts 20 hours under normal daily use."),
        ]
    )

    assert report.status == "disagreement"
    assert report.source_count == 2
    assert report.consensus_weight <= 0.5
    assert len(report.conflicts) == 1
    conflict = report.conflicts[0]
    assert {conflict.side_a.source_id, conflict.side_b.source_id} == {"source-a", "source-b"}

    rendered = engine.conflict_preserving_answer(report)
    assert "Battery Test A" in rendered and "10 hours" in rendered
    assert "Battery Test B" in rendered and "20 hours" in rendered


def test_ask_workspace_exposes_consensus_weight_and_conflict_evidence() -> None:
    ask_js = (STATIC / "js" / "views" / "ask.js").read_text(encoding="utf-8")

    assert "chat.consensus" in ask_js
    assert "consensus.consensus_weight" in ask_js
    assert "consensus.source_count" in ask_js
    assert "c.side_a?.claim" in ask_js
    assert "c.side_b?.claim" in ask_js
