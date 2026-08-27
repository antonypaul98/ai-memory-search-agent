"""Tests for deterministic claim-level answer verification."""

from app.services.verification_engine import VerificationEngine


class TestVerificationEngine:
    def test_supported_claim_maps_to_evidence(self) -> None:
        report = VerificationEngine().verify(
            "RAG retrieves relevant documents before generating an answer.",
            [
                {
                    "video_id": "v1",
                    "start_time": 42.0,
                    "matched_text": "RAG retrieves relevant documents before generating the final answer.",
                }
            ],
        )
        assert report.supported_count == 1
        assert report.unsupported_count == 0
        assert report.claims[0].status == "supported"
        assert report.claims[0].evidence_ids == ["v1@42"]

    def test_adversarial_unsupported_claim_is_flagged(self) -> None:
        report = VerificationEngine().verify(
            "The system guarantees 99.999% uptime on Mars.",
            [
                {
                    "video_id": "v1",
                    "start_time": 1.0,
                    "matched_text": "The tutorial explains local vector search with SQLite.",
                }
            ],
        )
        assert report.unsupported_count == 1
        assert report.claims[0].status == "unsupported"
        assert report.claims[0].evidence_ids == []

    def test_claim_number_missing_from_evidence_is_not_supported(self) -> None:
        report = VerificationEngine().verify(
            "The benchmark processed 5000 documents.",
            [
                {
                    "video_id": "v1",
                    "matched_text": "The benchmark processed 500 documents successfully.",
                }
            ],
        )
        assert report.claims[0].status != "supported"

    def test_each_sentence_is_mapped_or_flagged(self) -> None:
        report = VerificationEngine().verify(
            "Embeddings encode text into vectors. Penguins run the database cluster.",
            [
                {
                    "video_id": "v1",
                    "matched_text": "Embeddings encode text into numerical vectors for semantic search.",
                }
            ],
        )
        assert len(report.claims) == 2
        assert report.claims[0].status == "supported"
        assert report.claims[0].evidence_ids
        assert report.claims[1].status == "unsupported"
        assert report.claims[1].evidence_ids == []

    def test_empty_answer_returns_zero_score(self) -> None:
        report = VerificationEngine().verify("", [])
        assert report.score == 0.0
        assert report.claims == []
