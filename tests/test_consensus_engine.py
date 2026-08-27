"""Regression tests for deterministic cross-source consensus analysis."""

from app.services.consensus_engine import ConsensusEngine


def _hit(video_id: str, title: str, text: str) -> dict:
    return {
        "video_id": video_id,
        "title": title,
        "matched_text": text,
        "relevance_score": 0.9,
    }


class TestConsensusEngine:
    def test_requires_two_independent_sources(self) -> None:
        report = ConsensusEngine().analyze([
            _hit("v1", "One", "RAG retrieves documents before generation.")
        ])
        assert report.status == "insufficient_sources"
        assert report.source_count == 1
        assert report.consensus_weight == 0.0

    def test_detects_cross_source_agreement_and_weight(self) -> None:
        report = ConsensusEngine().analyze(
            [
                _hit("v1", "One", "RAG retrieves relevant documents before generating an answer."),
                _hit("v2", "Two", "RAG retrieves relevant documents before generating an answer."),
            ]
        )
        assert report.status == "agreement"
        assert report.source_count == 2
        assert report.consensus_weight == 1.0
        assert report.agreements[0].source_ids == ["v1", "v2"]

    def test_detects_numeric_disagreement_without_merging(self) -> None:
        engine = ConsensusEngine()
        report = engine.analyze(
            [
                _hit("v1", "Source A", "The battery lasts 10 hours under normal daily use."),
                _hit("v2", "Source B", "The battery lasts 20 hours under normal daily use."),
            ]
        )
        assert report.status == "disagreement"
        assert report.conflicts[0].reason == "numeric_mismatch"
        answer = engine.conflict_preserving_answer(report)
        assert "Source A" in answer and "10 hours" in answer
        assert "Source B" in answer and "20 hours" in answer
        assert "disagree" in answer.lower()

    def test_detects_negation_disagreement(self) -> None:
        report = ConsensusEngine().analyze(
            [
                _hit("v1", "One", "The feature is supported in offline mode for local users."),
                _hit("v2", "Two", "The feature is not supported in offline mode for local users."),
            ]
        )
        assert report.status == "disagreement"
        assert report.conflicts[0].reason == "negation_mismatch"

    def test_unrelated_sources_are_inconclusive_not_false_consensus(self) -> None:
        report = ConsensusEngine().analyze(
            [
                _hit("v1", "One", "Postgres supports transactional relational storage."),
                _hit("v2", "Two", "A transformer uses attention to encode token context."),
            ]
        )
        assert report.status == "inconclusive"
        assert report.agreements == []
        assert report.conflicts == []

    def test_multiple_chunks_from_same_video_do_not_fake_independence(self) -> None:
        report = ConsensusEngine().analyze(
            [
                _hit("v1", "One", "RAG retrieves documents before generation."),
                _hit("v1", "One", "RAG retrieves documents before generation."),
            ]
        )
        assert report.status == "insufficient_sources"
        assert report.source_count == 1
