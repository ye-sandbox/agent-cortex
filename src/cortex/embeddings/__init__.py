"""Embedding engines and ONNX CPU pipelines for agent-cortex."""

from cortex.embeddings.engine import (
    EmbeddingEngine,
    EmbedPassageFn,
    EmbedQueryFn,
)

__all__ = [
    "EmbedPassageFn",
    "EmbedQueryFn",
    "EmbeddingEngine",
]
