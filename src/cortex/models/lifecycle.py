"""Model lifecycle management and pre-caching routines for agent-cortex."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from cortex.models.profile import HardwareProfile
from cortex.retrieval.reranker import RERANKER_MODEL_ALIASES

logger = logging.getLogger(__name__)


class ModelDownloadError(RuntimeError):
    """Raised when an ONNX model cannot be downloaded or cached."""

    def __init__(self, model_name: str, message: str, cause: Exception | None = None) -> None:
        self.model_name = model_name
        self.message = message
        self.cause = cause
        super().__init__(f"Failed to download model '{model_name}': {message}")


def download_embedding_model(
    model_name: str,
    cache_dir: Path | str | None = None,
) -> Path:
    """Download and cache embedding model weights locally using FastEmbed.

    Args:
        model_name: Identifier of the FastEmbed embedding model.
        cache_dir: Optional custom local directory for ONNX cache.

    Returns:
        Path to the cached model directory.

    Raises:
        ModelDownloadError: If model cannot be downloaded due to network or invalid identifier.
    """
    try:
        from fastembed import TextEmbedding

        cache_str = str(cache_dir) if cache_dir else None
        embedding = TextEmbedding(
            model_name=model_name,
            cache_dir=cache_str,
            lazy_load=True,
        )
        model_dir = getattr(embedding.model, "_model_dir", None)
        if isinstance(model_dir, Path):
            return model_dir
        return Path(str(model_dir)) if model_dir else Path(cache_str or ".")
    except Exception as exc:
        raise ModelDownloadError(
            model_name=model_name,
            message=str(exc),
            cause=exc,
        ) from exc


def download_reranker_model(
    model_name: str,
    cache_dir: Path | str | None = None,
) -> Path:
    """Download and cache cross-encoder reranker model weights locally.

    Args:
        model_name: Identifier of the cross-encoder model (or alias).
        cache_dir: Optional custom local directory for ONNX cache.

    Returns:
        Path to the cached model directory.

    Raises:
        ModelDownloadError: If model cannot be downloaded due to network or invalid identifier.
    """
    resolved_name = RERANKER_MODEL_ALIASES.get(model_name, model_name)
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        cache_str = str(cache_dir) if cache_dir else None
        reranker = TextCrossEncoder(
            model_name=resolved_name,
            cache_dir=cache_str,
            lazy_load=True,
        )
        model_dir = getattr(reranker.model, "_model_dir", None)
        if isinstance(model_dir, Path):
            return model_dir
        return Path(str(model_dir)) if model_dir else Path(cache_str or ".")
    except Exception as exc:
        raise ModelDownloadError(
            model_name=model_name,
            message=str(exc),
            cause=exc,
        ) from exc


def download_profile_models(
    profile: HardwareProfile,
    cache_dir: Path | str | None = None,
    on_progress: Callable[[str, str], None] | None = None,
) -> dict[str, Path]:
    """Download and pre-cache all models required by a hardware profile.

    Args:
        profile: The HardwareProfile specifying embedding and reranker models.
        cache_dir: Optional custom cache directory.
        on_progress: Optional callback invoked with (stage, model_name) before each download.

    Returns:
        Dictionary mapping model role ('embedding', 'reranker') to cached directory path.
    """
    results: dict[str, Path] = {}

    if on_progress:
        on_progress("embedding", profile.embedding_model)
    emb_path = download_embedding_model(profile.embedding_model, cache_dir=cache_dir)
    results["embedding"] = emb_path

    if profile.reranker_enabled and profile.reranker_model:
        if on_progress:
            on_progress("reranker", profile.reranker_model)
        rerank_path = download_reranker_model(profile.reranker_model, cache_dir=cache_dir)
        results["reranker"] = rerank_path

    return results
