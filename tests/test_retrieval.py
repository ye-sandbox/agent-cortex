"""Unit tests for Stage 1 Hybrid Retrieval pipeline and Reciprocal Rank Fusion (RRF)."""

from collections.abc import Sequence
from tempfile import TemporaryDirectory

from cortex.config.loader import RetrievalConfig
from cortex.embeddings.engine import EmbeddingEngine
from cortex.models.chunk import (
    ChunkCategory,
    ChunkLifecycle,
    ChunkScope,
)
from cortex.retrieval.pipeline import (
    HybridRetrievalPipeline,
    build_where_clause,
)
from cortex.storage.manager import StorageManager


def test_build_where_clause() -> None:
    """Test SQL WHERE clause synthesis, defaults, and escaping."""
    default_clause = build_where_clause()
    assert default_clause == "scope IN ('internal', 'public')"

    custom_scope = build_where_clause(scopes=[ChunkScope.PUBLIC])
    assert custom_scope == "scope IN ('public')"

    filtered_clause = build_where_clause(
        scopes=[ChunkScope.INTERNAL],
        category=ChunkCategory.CONTRACT,
        repo="sentinel's-app",
    )
    assert (
        filtered_clause
        == "scope IN ('internal') AND category = 'contract' AND repo = 'sentinel''s-app'"
    )


def test_hybrid_retrieval_fusion_and_scoring() -> None:
    """Test end-to-end hybrid retrieval with RRF fusion, lifecycle penalty, and scope isolation."""
    with TemporaryDirectory() as tmpdir:
        storage = StorageManager(data_dir=tmpdir)

        # Mock embedding engine: 2D vector based on query length/content
        def mock_passage_embed(texts: Sequence[str]) -> list[list[float]]:
            results: list[list[float]] = []
            for t in texts:
                if "openapi" in t.lower():
                    results.append([1.0, 0.0])
                elif "redis" in t.lower():
                    results.append([0.0, 1.0])
                else:
                    results.append([0.5, 0.5])
            return results

        def mock_query_embed(query: str) -> list[float]:
            if "openapi" in query.lower():
                return [1.0, 0.0]
            if "redis" in query.lower():
                return [0.0, 1.0]
            return [0.5, 0.5]

        embeddings = EmbeddingEngine(
            passage_embed_fn=mock_passage_embed,
            query_embed_fn=mock_query_embed,
        )

        from cortex.models.chunk import DocumentChunk

        raw_chunks = [
            DocumentChunk(
                id="sentinel:specs/openapi.json:get_deals",
                repo="sentinel",
                file_path="specs/openapi.json",
                category=ChunkCategory.CONTRACT,
                lifecycle=ChunkLifecycle.ACTIVE,
                scope=ChunkScope.INTERNAL,
                breadcrumb="GET /deals",
                commit_sha="c1",
                tags=["openapi", "deals"],
                content="Active openapi deals endpoint contract",
                vector=None,
            ),
            DocumentChunk(
                id="sentinel:compose.yaml:redis",
                repo="sentinel",
                file_path="compose.yaml",
                category=ChunkCategory.INFRA,
                lifecycle=ChunkLifecycle.ACTIVE,
                scope=ChunkScope.INTERNAL,
                breadcrumb="services > redis",
                commit_sha="c2",
                tags=["redis"],
                content="Redis caching infrastructure configuration",
                vector=None,
            ),
            DocumentChunk(
                id="sentinel:legacy/openapi.json:v1_deals",
                repo="sentinel",
                file_path="legacy/openapi.json",
                category=ChunkCategory.CONTRACT,
                lifecycle=ChunkLifecycle.ARCHIVED,
                scope=ChunkScope.INTERNAL,
                breadcrumb="GET /v1/deals",
                commit_sha="c3",
                tags=["openapi", "archived"],
                content="Archived openapi deals endpoint legacy contract",
                vector=None,
            ),
            DocumentChunk(
                id="sentinel:secrets/auth.md:tokens",
                repo="sentinel",
                file_path="secrets/auth.md",
                category=ChunkCategory.INVARIANT,
                lifecycle=ChunkLifecycle.ACTIVE,
                scope=ChunkScope.CONFIDENTIAL,
                breadcrumb="Auth tokens",
                commit_sha="c4",
                tags=["openapi", "auth"],
                content="Confidential openapi authentication tokens",
                vector=None,
            ),
        ]

        embedded_chunks = embeddings.embed_chunks(raw_chunks)
        storage.upsert_chunks(embedded_chunks, dim=2)

        config = RetrievalConfig(
            k=60,
            weight_dense=0.65,
            weight_sparse=0.35,
            archived_penalty=0.6,
            default_limit=10,
        )
        pipeline = HybridRetrievalPipeline(storage=storage, embeddings=embeddings, config=config)

        # 1. Search with empty query
        assert pipeline.search("") == []
        assert pipeline.search("   ") == []

        # 2. Search for "openapi" (default scopes: internal, public)
        results = pipeline.search("openapi", limit=5)
        # Confidential chunk must NOT be present
        assert not any(r.id == "sentinel:secrets/auth.md:tokens" for r in results)

        # Active openapi chunk must rank highest
        assert len(results) >= 2
        assert results[0].id == "sentinel:specs/openapi.json:get_deals"
        assert results[0].lifecycle == ChunkLifecycle.ACTIVE
        assert results[0].score > 0.0

        # Verify anchor formatting
        anchor = results[0].format_anchor()
        assert anchor == "[sentinel] specs/openapi.json > GET /deals"

        # Archived chunk score must be lower due to 0.6 penalty
        archived_results = [r for r in results if r.lifecycle == ChunkLifecycle.ARCHIVED]
        assert len(archived_results) == 1
        archived_item = archived_results[0]
        assert results[0].score > archived_item.score

        # 3. Search with include_archived=True
        results_with_archived = pipeline.search("openapi", include_archived=True)
        archived_unpenalized = next(
            r for r in results_with_archived if r.lifecycle == ChunkLifecycle.ARCHIVED
        )
        assert archived_unpenalized.score > archived_item.score

        # 4. Search with confidential scope permitted
        conf_results = pipeline.search("openapi", scopes=[ChunkScope.CONFIDENTIAL])
        assert any(r.id == "sentinel:secrets/auth.md:tokens" for r in conf_results)

        # 5. Search with category filter
        infra_results = pipeline.search("redis", category=ChunkCategory.INFRA)
        assert len(infra_results) == 1
        assert infra_results[0].category == ChunkCategory.INFRA
        assert infra_results[0].id == "sentinel:compose.yaml:redis"


def test_two_stage_retrieval_with_reranker() -> None:
    """Test 2-stage retrieval: Stage 1 RRF candidate pool + Stage 2 Cross-Encoder rerank."""
    with TemporaryDirectory() as tmpdir:
        storage = StorageManager(data_dir=tmpdir)

        embeddings = EmbeddingEngine(
            passage_embed_fn=lambda texts: [[0.5, 0.5] for _ in texts],
            query_embed_fn=lambda q: [0.5, 0.5],
        )

        from cortex.models.chunk import DocumentChunk

        chunks = [
            DocumentChunk(
                id="sentinel:docs/guide.md:intro",
                repo="sentinel",
                file_path="docs/guide.md",
                category=ChunkCategory.DOC,
                lifecycle=ChunkLifecycle.ACTIVE,
                scope=ChunkScope.INTERNAL,
                breadcrumb="Introduction",
                commit_sha="c1",
                tags=["guide"],
                content="Basic introductory documentation about sentinel architecture.",
                vector=None,
            ),
            DocumentChunk(
                id="sentinel:specs/openapi.json:deals",
                repo="sentinel",
                file_path="specs/openapi.json",
                category=ChunkCategory.CONTRACT,
                lifecycle=ChunkLifecycle.ACTIVE,
                scope=ChunkScope.INTERNAL,
                breadcrumb="GET /deals",
                commit_sha="c2",
                tags=["deals"],
                content="Exact specification for deals querying endpoint.",
                vector=None,
            ),
        ]

        storage.upsert_chunks(embeddings.embed_chunks(chunks), dim=2)

        # Cross-encoder scoring hook that scores 'exact specification' highest
        def mock_rerank(query: str, passages: Sequence[str]) -> list[float]:
            scores: list[float] = []
            for p in passages:
                if "exact specification" in p.lower():
                    scores.append(0.99)
                else:
                    scores.append(0.20)
            return scores

        from cortex.models.profile import HardwareProfileName
        from cortex.retrieval.reranker import RerankerEngine

        reranker = RerankerEngine(
            profile=HardwareProfileName.BALANCED,
            rerank_fn=mock_rerank,
        )

        pipeline = HybridRetrievalPipeline(
            storage=storage,
            embeddings=embeddings,
            reranker=reranker,
        )

        # 1. Search with reranker enabled (default)
        reranked_results = pipeline.search("deals", limit=2)
        assert len(reranked_results) == 2
        # Cross-encoder should place the exact specification first with score 0.99
        assert reranked_results[0].id == "sentinel:specs/openapi.json:deals"
        assert reranked_results[0].score == 0.99

        # 2. Search with rerank=False (bypass reranker)
        stage1_only = pipeline.search("deals", limit=2, rerank=False)
        assert len(stage1_only) == 2
        # Score is RRF score rather than cross-encoder score
        assert stage1_only[0].score < 0.99
