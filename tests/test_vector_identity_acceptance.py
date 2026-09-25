"""G02: real Chroma collision, replay, canonical-reference and legacy-read proof."""
from app.db.hierarchical_store import HierarchicalStore
from app.db.repositories.memory_repository import MemoryRepository
from app.db.chroma_client import get_collection
from app.models.capsule import MemoryCapsule, MemorySection
from app.models.video import VideoMetadata
from app.services.universal_memory_service import UniversalMemoryService
from app.utils.chunking import TranscriptChunk


def test_ambiguous_components_cannot_overwrite_neighbor_and_refs_resolve(test_settings):
    repo = MemoryRepository(test_settings)
    hierarchy = HierarchicalStore(test_settings)
    canonical = UniversalMemoryService(test_settings)
    identities = (("a_b", "c"), ("a", "b_c"))
    # These distinct identities collided in every previous delimiter-joined ID.
    assert "_".join(identities[0]) == "_".join(identities[1])
    refs = []
    for owner, external in identities:
        title = "private-" + owner
        capsule = MemoryCapsule(video_id=external, title=title, sections=[MemorySection(title=title, summary=title)])
        for _ in range(2):  # Deterministic replay cannot duplicate or overwrite a neighbor.
            repo.upsert_chunks(user_id=owner, video_id=external, url="https://example.test/" + external,
                title=title, channel="fixture", thumbnail="", duration=1, transcript_source="fixture",
                chunks=[TranscriptChunk(0, title, 0., 1.)], embeddings=[[1., 0., 0.]], embedding_model="fixture")
            hierarchy.upsert_capsule(capsule, [1., 0., 0.], user_id=owner)
            hierarchy.upsert_sections(external, capsule.sections, [[1., 0., 0.]], user_id=owner)
        memory = canonical.finalize_ingest(user_id=owner,
            metadata=VideoMetadata(video_id=external, title=title, channel="fixture", webpage_url="https://example.test/" + external),
            capsule=capsule, reflection=None, chunk_count=1, embedding_model="fixture", transcript_source="fixture", has_capsule=True)
        refs.append(memory.embedding_refs)
    for (owner, external), ref in zip(identities, refs):
        for name, ids in ((test_settings.capsule_collection_name, [ref.capsule_doc_id]),
                          (test_settings.section_collection_name, ref.section_doc_ids),
                          (test_settings.chroma_collection_name, ref.evidence_doc_ids)):
            collection = hierarchy._collection(name)
            assert collection.count() == 2
            stored = collection.get(ids=ids, include=["metadatas"])
            assert stored["ids"] == ids
            assert all(meta["user_id"] == owner and meta["video_id"] == external for meta in stored["metadatas"])
        for name in (test_settings.capsule_collection_name, test_settings.section_collection_name):
            hits = hierarchy.search_level(name, [1., 0., 0.], top_k=10, user_id=owner)
            assert len(hits) == 1 and hits[0]["user_id"] == owner
            assert hits[0]["video_id"] == external
        hits = repo.search([1., 0., 0.], 10, user_id=owner)
        assert len(hits) == 1 and hits[0]["title"] == "private-" + owner
    hierarchy.delete_video("c", user_id="a_b")
    repo.delete_item("c", user_id="a_b")
    assert repo.search([1., 0., 0.], 10, user_id="a")
    assert hierarchy.search_level(test_settings.section_collection_name, [1., 0., 0.], top_k=10, user_id="a")


def test_preexisting_owned_vector_ids_remain_readable(test_settings):
    hierarchy = HierarchicalStore(test_settings)
    old_id = "capsule_legacy_source"
    hierarchy._collection(test_settings.capsule_collection_name).upsert(
        ids=[old_id], embeddings=[[1., 0., 0.]], documents=["old evidence"],
        metadatas=[{"doc_id": old_id, "user_id": "legacy", "video_id": "source", "level": "capsule"}])
    hits = hierarchy.search_level(test_settings.capsule_collection_name, [1., 0., 0.], top_k=10, user_id="legacy")
    assert [hit["doc_id"] for hit in hits] == [old_id]
    assert hierarchy.search_level(test_settings.capsule_collection_name, [1., 0., 0.], top_k=10, user_id="neighbor") == []
