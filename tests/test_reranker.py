"""Unit tests for Stage 2 Cross-Encoder Precision Reranker and Profile Controller."""

from __future__ import annotations

from collections.abc import Sequence

from cortex.models.chunk import (
    ChunkCategory,
    ChunkLifecycle,
    ChunkScope,
    SearchResultChunk,
)
from cortex.models.profile import (
    HardwareProfile,
    HardwareProfileName,
)
from cortex.retrieval.reranker import (
    RERANKER_MODEL_ALIASES,
    RerankerEngine,
)


def _make_dummy_chunk(chunk_id: str, content: str, score: float = 0.5) -> SearchResultChunk:
    """Helper to construct SearchResultChunk instances for tests."""
    return SearchResultChunk(
        id=chunk_id,
        repo="test-repo",
        file_path="docs/test.md",
        category=ChunkCategory.DOC,
        lifecycle=ChunkLifecycle.ACTIVE,
        scope=ChunkScope.INTERNAL,
        breadcrumb="Section",
        score=score,
        content=content,
        snippet=content[:50],
        tags=["test"],
    )


def test_reranker_profile_routing() -> None:
    """Verifies profile configuration and alias resolution across hardware tiers."""
    # 1. Balanced profile (default)
    reranker_balanced = RerankerEngine(HardwareProfileName.BALANCED)
    assert reranker_balanced.is_enabled is True
    assert reranker_balanced.model_name == "BAAI/bge-reranker-base"
    assert reranker_balanced.resolved_model_name == "BAAI/bge-reranker-base"
    assert reranker_balanced.candidate_pool_size == 20

    # 2. High profile (aliased to bge-reranker-v2-m3)
    reranker_high = RerankerEngine(HardwareProfileName.HIGH)
    assert reranker_high.is_enabled is True
    assert reranker_high.model_name == "BAAI/bge-reranker-large"
    assert reranker_high.resolved_model_name == "BAAI/bge-reranker-v2-m3"
    assert reranker_high.candidate_pool_size == 30

    # 3. Low profile (bypassed)
    reranker_low = RerankerEngine(HardwareProfileName.LOW)
    assert reranker_low.is_enabled is False
    assert reranker_low.model_name is None
    assert reranker_low.resolved_model_name is None
    assert reranker_low.candidate_pool_size == 0

    # 4. Custom profile
    custom = HardwareProfile(
        name="custom-tier",
        embedding_model="custom/embed",
        embedding_dim=512,
        reranker_model="custom/rerank",
        reranker_enabled=True,
        top_k_rerank=25,
        max_threads=2,
    )
    reranker_custom = RerankerEngine(custom)
    assert reranker_custom.is_enabled is True
    assert reranker_custom.model_name == "custom/rerank"
    assert reranker_custom.candidate_pool_size == 25


def test_reranker_zero_overhead_bypass_on_low_profile() -> None:
    """Verifies that the low hardware profile executes zero-overhead bypass without model init."""
    reranker = RerankerEngine(HardwareProfileName.LOW)
    assert reranker._model is None

    chunks = [
        _make_dummy_chunk("c1", "First document", score=0.9),
        _make_dummy_chunk("c2", "Second document", score=0.8),
        _make_dummy_chunk("c3", "Third document", score=0.7),
    ]

    # Rerank with top_k=2 should immediately slice without modifying scores or touching any model
    results = reranker.rerank("search query", chunks, top_k=2)
    assert len(results) == 2
    assert results[0].id == "c1"
    assert results[0].score == 0.9
    assert results[1].id == "c2"
    assert results[1].score == 0.8
    assert reranker._model is None


def test_reranker_empty_inputs() -> None:
    """Verifies behavior on empty chunk sequences or empty queries."""
    reranker = RerankerEngine(HardwareProfileName.BALANCED)

    # Empty chunks
    assert reranker.rerank("query", []) == []

    # Empty or whitespace query returns input sliced to top_k without scoring
    chunks = [
        _make_dummy_chunk("c1", "Content 1", score=0.8),
        _make_dummy_chunk("c2", "Content 2", score=0.6),
    ]
    results_empty = reranker.rerank("   ", chunks, top_k=1)
    assert len(results_empty) == 1
    assert results_empty[0].id == "c1"
    assert results_empty[0].score == 0.8


def test_reranker_precision_scoring_and_reordering() -> None:
    """Verifies cross-encoder precision score calculation, candidate reordering, and pruning."""

    def mock_scoring(query: str, passages: Sequence[str]) -> list[float]:
        # Give higher score to passage mentioning 'precision'
        scores: list[float] = []
        for p in passages:
            if "precision" in p.lower():
                scores.append(0.987654)
            elif "fast" in p.lower():
                scores.append(0.754321)
            else:
                scores.append(0.123456)
        return scores

    reranker = RerankerEngine(
        profile=HardwareProfileName.BALANCED,
        rerank_fn=mock_scoring,
    )

    # Stage 1 initial candidate order: c1 had high RRF score,
    # but c2 has exact cross-encoder relevance
    candidates = [
        _make_dummy_chunk("c1", "General overview text", score=0.95),
        _make_dummy_chunk("c2", "Text with high precision match", score=0.50),
        _make_dummy_chunk("c3", "Text with fast execution notes", score=0.30),
    ]

    reranked = reranker.rerank("query", candidates, top_k=2)

    # Cross-encoder should have reordered c2 to rank 1, followed by c3, pruned to top 2
    assert len(reranked) == 2
    assert reranked[0].id == "c2"
    assert reranked[0].score == 0.987654
    assert reranked[1].id == "c3"
    assert reranked[1].score == 0.754321

    # Verify that model was never initialized since rerank_fn was used
    assert reranker._model is None


def test_reranker_model_alias_mapping() -> None:
    """Verifies that model alias mapping contains expected pairs."""
    assert "BAAI/bge-reranker-large" in RERANKER_MODEL_ALIASES
    assert RERANKER_MODEL_ALIASES["BAAI/bge-reranker-large"] == "BAAI/bge-reranker-v2-m3"
