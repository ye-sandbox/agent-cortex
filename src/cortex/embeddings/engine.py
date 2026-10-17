"""ONNX CPU embedding engine powered by FastEmbed for agent-cortex."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from cortex.models.chunk import DocumentChunk
from cortex.models.profile import (
    HardwareProfile,
    HardwareProfileName,
    resolve_hardware_profile,
)

logger = logging.getLogger(__name__)

# Type aliases for testing hooks
EmbedPassageFn = Callable[[Sequence[str]], list[list[float]]]
EmbedQueryFn = Callable[[str], list[float]]


class EmbeddingEngine:
    """Manages ONNX CPU embedding generation using FastEmbed with hardware profiles."""

    def __init__(
        self,
        profile: HardwareProfile | HardwareProfileName | str | None = None,
        cache_dir: Path | str | None = None,
        passage_embed_fn: EmbedPassageFn | None = None,
        query_embed_fn: EmbedQueryFn | None = None,
    ) -> None:
        """Initialize EmbeddingEngine with resolved profile and optional testing hooks."""
        if profile is None:
            self.profile = resolve_hardware_profile(HardwareProfileName.BALANCED)
        elif isinstance(profile, HardwareProfile):
            self.profile = profile
        else:
            self.profile = resolve_hardware_profile(profile)

        self.cache_dir = Path(cache_dir).expanduser() if cache_dir else None
        self._passage_embed_fn = passage_embed_fn
        self._query_embed_fn = query_embed_fn

        self._model: Any = None

    @property
    def model_name(self) -> str:
        """Return the active embedding model identifier."""
        return self.profile.embedding_model

    @property
    def dim(self) -> int:
        """Return the vector dimensionality."""
        return self.profile.embedding_dim

    def _get_model(self) -> Any:
        """Lazily initialize FastEmbed TextEmbedding instance with profile thread bounds."""
        if self._model is None:
            from fastembed import TextEmbedding

            cache_str = str(self.cache_dir) if self.cache_dir else None
            logger.info(
                "Initializing FastEmbed model '%s' with %d threads",
                self.model_name,
                self.profile.max_threads,
            )
            self._model = TextEmbedding(
                model_name=self.model_name,
                cache_dir=cache_str,
                threads=self.profile.max_threads,
                cuda=False,
            )
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Compute dense passage embeddings for a batch of text documents."""
        if not texts:
            return []

        if self._passage_embed_fn is not None:
            return self._passage_embed_fn(texts)

        model = self._get_model()
        embeddings_iter = model.passage_embed(texts)
        result: list[list[float]] = [[float(v) for v in emb] for emb in embeddings_iter]
        return result

    def embed_chunks(self, chunks: Sequence[DocumentChunk]) -> list[DocumentChunk]:
        """Compute and populate embeddings for a sequence of DocumentChunk instances."""
        if not chunks:
            return []

        # Find chunks needing embeddings
        indices_to_embed: list[int] = []
        texts_to_embed: list[str] = []
        for i, chunk in enumerate(chunks):
            if chunk.vector is None:
                indices_to_embed.append(i)
                texts_to_embed.append(chunk.content)

        if not texts_to_embed:
            return list(chunks)

        computed_vectors = self.embed_documents(texts_to_embed)

        updated_chunks = list(chunks)
        for idx, vec in zip(indices_to_embed, computed_vectors, strict=True):
            updated_chunks[idx] = chunks[idx].model_copy(update={"vector": vec})

        return updated_chunks

    def embed_query(self, query: str) -> list[float]:
        """Compute dense query embedding for a search string."""
        if self._query_embed_fn is not None:
            return self._query_embed_fn(query)

        model = self._get_model()
        embeddings_iter = model.query_embed(query)
        first_emb = next(iter(embeddings_iter))
        return [float(v) for v in first_emb]
