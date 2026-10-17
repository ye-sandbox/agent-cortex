"""Stage 2 Cross-Encoder Precision Reranker engine for agent-cortex."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from cortex.models.chunk import SearchResultChunk
from cortex.models.profile import (
    HardwareProfile,
    HardwareProfileName,
    resolve_hardware_profile,
)

logger = logging.getLogger(__name__)

# Model alias mapping for FastEmbed cross-encoder registry
RERANKER_MODEL_ALIASES: dict[str, str] = {
    "BAAI/bge-reranker-large": "BAAI/bge-reranker-v2-m3",
}

# Type alias for test hooks and hermetic execution
RerankFn = Callable[[str, Sequence[str]], list[float]]


class RerankerEngine:
    """Manages Stage 2 Cross-Encoder precision scoring using FastEmbed TextCrossEncoder."""

    def __init__(
        self,
        profile: HardwareProfile | HardwareProfileName | str | None = None,
        cache_dir: Path | str | None = None,
        rerank_fn: RerankFn | None = None,
    ) -> None:
        """Initialize RerankerEngine with resolved profile and optional testing hook."""
        if profile is None:
            self.profile = resolve_hardware_profile(HardwareProfileName.BALANCED)
        elif isinstance(profile, HardwareProfile):
            self.profile = profile
        else:
            self.profile = resolve_hardware_profile(profile)

        self.cache_dir = Path(cache_dir).expanduser() if cache_dir else None
        self._rerank_fn = rerank_fn
        self._model: Any = None

    @property
    def is_enabled(self) -> bool:
        """Return True if reranking is enabled and a reranker model is defined."""
        return self.profile.reranker_enabled and self.profile.reranker_model is not None

    @property
    def model_name(self) -> str | None:
        """Return configured reranker model identifier."""
        return self.profile.reranker_model

    @property
    def resolved_model_name(self) -> str | None:
        """Return upstream FastEmbed model identifier taking aliases into account."""
        if not self.profile.reranker_model:
            return None
        return RERANKER_MODEL_ALIASES.get(self.profile.reranker_model, self.profile.reranker_model)

    @property
    def candidate_pool_size(self) -> int:
        """Return candidate pool size (top_k_rerank) defined in profile."""
        return self.profile.top_k_rerank

    def _get_model(self) -> Any:
        """Lazily initialize FastEmbed TextCrossEncoder instance."""
        if self._model is None:
            model_id = self.resolved_model_name
            if not model_id:
                raise ValueError("Cannot initialize TextCrossEncoder without a reranker model")

            from fastembed.rerank.cross_encoder import TextCrossEncoder

            cache_str = str(self.cache_dir) if self.cache_dir else None
            logger.info(
                "Initializing FastEmbed TextCrossEncoder '%s' (threads=%d)",
                model_id,
                self.profile.max_threads,
            )
            self._model = TextCrossEncoder(
                model_name=model_id,
                cache_dir=cache_str,
                threads=self.profile.max_threads,
            )
        return self._model

    def score_passages(self, query: str, passages: Sequence[str]) -> list[float]:
        """Compute cross-encoder relevance scores for query and candidate passages."""
        if not passages:
            return []

        if self._rerank_fn is not None:
            return self._rerank_fn(query, passages)

        model = self._get_model()
        scores_iter = model.rerank(query=query, documents=passages)
        return [float(s) for s in scores_iter]

    def rerank(
        self,
        query: str,
        items: Sequence[SearchResultChunk],
        top_k: int | None = None,
    ) -> list[SearchResultChunk]:
        """Rerank candidates using cross-encoder scores and prune to top_k."""
        if not items:
            return []

        # Zero-overhead bypass if reranker is disabled
        if not self.is_enabled:
            if top_k is not None:
                return list(items[: max(0, top_k)])
            return list(items)

        cleaned_query = query.strip()
        if not cleaned_query:
            if top_k is not None:
                return list(items[: max(0, top_k)])
            return list(items)

        passages = [item.content if item.content else (item.snippet or "") for item in items]
        scores = self.score_passages(cleaned_query, passages)

        reranked: list[SearchResultChunk] = []
        for item, score in zip(items, scores, strict=True):
            reranked.append(item.model_copy(update={"score": round(score, 6)}))

        reranked.sort(key=lambda r: r.score, reverse=True)

        if top_k is not None:
            return reranked[: max(0, top_k)]
        return reranked

    @classmethod
    def download_model(
        cls,
        profile: HardwareProfile | HardwareProfileName | str | None = None,
        cache_dir: Path | str | None = None,
    ) -> Path | None:
        """Explicitly pre-cache the ONNX reranker model weights for a profile if enabled."""
        from cortex.models.lifecycle import download_reranker_model

        resolved = (
            profile
            if isinstance(profile, HardwareProfile)
            else resolve_hardware_profile(profile or HardwareProfileName.BALANCED)
        )
        if not resolved.reranker_enabled or not resolved.reranker_model:
            return None
        return download_reranker_model(resolved.reranker_model, cache_dir=cache_dir)
