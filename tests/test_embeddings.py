"""Unit tests for FastEmbed embedding engine and hardware profile routing."""

from cortex.embeddings.engine import EmbeddingEngine
from cortex.models.chunk import (
    ChunkCategory,
    DocumentChunk,
)
from cortex.models.profile import HardwareProfile, HardwareProfileName


def test_embedding_engine_profile_resolution() -> None:
    """Ensure EmbeddingEngine resolves predefined and custom hardware profiles."""
    engine_default = EmbeddingEngine()
    assert engine_default.profile.name == HardwareProfileName.BALANCED.value
    assert engine_default.model_name == "BAAI/bge-small-en-v1.5"
    assert engine_default.dim == 384

    engine_high = EmbeddingEngine(profile="high")
    assert engine_high.profile.name == HardwareProfileName.HIGH.value
    assert engine_high.dim == 1024

    engine_low = EmbeddingEngine(profile=HardwareProfileName.LOW)
    assert engine_low.profile.name == HardwareProfileName.LOW.value
    assert engine_low.dim == 384
    assert engine_low.profile.max_threads == 2

    custom_prof = HardwareProfile(
        name="custom_test",
        embedding_model="custom/model",
        embedding_dim=512,
        reranker_model=None,
        reranker_enabled=False,
        max_threads=1,
    )
    engine_custom = EmbeddingEngine(profile=custom_prof)
    assert engine_custom.model_name == "custom/model"
    assert engine_custom.dim == 512


def test_embedding_engine_lazy_loading() -> None:
    """Verify that FastEmbed model is not instantiated until invoked."""
    engine = EmbeddingEngine()
    assert engine._model is None


def test_embedding_engine_with_mock_functions() -> None:
    """Test embedding execution with hermetic mock functions to avoid network downloads."""

    def mock_passage_embed(texts: list[str]) -> list[list[float]]:
        return [[float(len(t)), 0.5, 0.25] for t in texts]

    def mock_query_embed(query: str) -> list[float]:
        return [float(len(query)), 1.0, 0.0]

    engine = EmbeddingEngine(
        passage_embed_fn=mock_passage_embed,
        query_embed_fn=mock_query_embed,
    )

    # Empty inputs
    assert engine.embed_documents([]) == []
    assert engine.embed_chunks([]) == []

    # Document embedding
    embs = engine.embed_documents(["hello", "world long"])
    assert len(embs) == 2
    assert embs[0] == [5.0, 0.5, 0.25]
    assert embs[1] == [10.0, 0.5, 0.25]

    # Query embedding
    q_emb = engine.embed_query("search")
    assert q_emb == [6.0, 1.0, 0.0]

    # Chunk embedding: only chunks with vector=None should be embedded
    chunk1 = DocumentChunk(
        id="cortex:a.md:0",
        repo="cortex",
        file_path="a.md",
        category=ChunkCategory.DOC,
        commit_sha="111",
        content="abc",
        vector=None,
    )
    chunk2 = DocumentChunk(
        id="cortex:b.md:0",
        repo="cortex",
        file_path="b.md",
        category=ChunkCategory.DOC,
        commit_sha="222",
        content="already embedded",
        vector=[9.9, 9.9, 9.9],
    )

    embedded_chunks = engine.embed_chunks([chunk1, chunk2])
    assert len(embedded_chunks) == 2
    assert embedded_chunks[0].vector == [3.0, 0.5, 0.25]
    assert embedded_chunks[1].vector == [9.9, 9.9, 9.9]
