"""Hermetic unit tests for cortex.models.lifecycle."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cortex.embeddings.engine import EmbeddingEngine
from cortex.models.lifecycle import (
    ModelDownloadError,
    download_embedding_model,
    download_profile_models,
    download_reranker_model,
)
from cortex.models.profile import HardwareProfileName, resolve_hardware_profile
from cortex.retrieval.reranker import RerankerEngine


def test_download_embedding_model_success() -> None:
    mock_instance = MagicMock()
    mock_instance.model._model_dir = Path("/tmp/mock_cache/bge-small-en-v1.5")

    with patch("fastembed.TextEmbedding", return_value=mock_instance) as mock_cls:
        res = download_embedding_model("BAAI/bge-small-en-v1.5", cache_dir="/tmp/mock_cache")
        assert res == Path("/tmp/mock_cache/bge-small-en-v1.5")
        mock_cls.assert_called_once_with(
            model_name="BAAI/bge-small-en-v1.5",
            cache_dir="/tmp/mock_cache",
            lazy_load=True,
        )


def test_download_embedding_model_failure() -> None:
    with patch("fastembed.TextEmbedding", side_effect=ValueError("Download failed")):
        with pytest.raises(ModelDownloadError) as exc_info:
            download_embedding_model("BAAI/bge-small-en-v1.5")

        assert "Failed to download model 'BAAI/bge-small-en-v1.5'" in str(exc_info.value)
        assert exc_info.value.model_name == "BAAI/bge-small-en-v1.5"
        assert isinstance(exc_info.value.cause, ValueError)


def test_download_embedding_model_success_with_alias() -> None:
    mock_instance = MagicMock()
    mock_instance.model._model_dir = Path("/tmp/mock_cache/bge-large-en-v1.5")

    with patch("fastembed.TextEmbedding", return_value=mock_instance) as mock_cls:
        # BAAI/bge-m3 maps to BAAI/bge-large-en-v1.5
        res = download_embedding_model("BAAI/bge-m3", cache_dir="/tmp/mock_cache")
        assert res == Path("/tmp/mock_cache/bge-large-en-v1.5")
        mock_cls.assert_called_once_with(
            model_name="BAAI/bge-large-en-v1.5",
            cache_dir="/tmp/mock_cache",
            lazy_load=True,
        )


def test_download_reranker_model_success_with_alias() -> None:
    mock_instance = MagicMock()
    mock_instance.model._model_dir = Path("/tmp/mock_cache/bge-reranker-large")

    with patch(
        "fastembed.rerank.cross_encoder.TextCrossEncoder", return_value=mock_instance
    ) as mock_cls:
        # BAAI/bge-reranker-large maps to BAAI/bge-reranker-v2-m3-int8
        res = download_reranker_model("BAAI/bge-reranker-large", cache_dir="/tmp/mock_cache")
        assert res == Path("/tmp/mock_cache/bge-reranker-large")
        mock_cls.assert_called_once_with(
            model_name="BAAI/bge-reranker-v2-m3-int8",
            cache_dir="/tmp/mock_cache",
            lazy_load=True,
        )


def test_download_reranker_model_failure() -> None:
    with patch(
        "fastembed.rerank.cross_encoder.TextCrossEncoder", side_effect=OSError("Network timeout")
    ):
        with pytest.raises(ModelDownloadError) as exc_info:
            download_reranker_model("BAAI/bge-reranker-base")

        assert "Network timeout" in str(exc_info.value)
        assert exc_info.value.model_name == "BAAI/bge-reranker-base"


def test_download_profile_models_balanced() -> None:
    profile = resolve_hardware_profile(HardwareProfileName.BALANCED)
    progress_calls: list[tuple[str, str]] = []

    def on_progress(stage: str, model: str) -> None:
        progress_calls.append((stage, model))

    with (
        patch(
            "cortex.models.lifecycle.download_embedding_model",
            return_value=Path("/tmp/emb"),
        ) as mock_emb,
        patch(
            "cortex.models.lifecycle.download_reranker_model",
            return_value=Path("/tmp/rerank"),
        ) as mock_rerank,
    ):
        results = download_profile_models(profile, cache_dir="/tmp/cache", on_progress=on_progress)

        assert results == {
            "embedding": Path("/tmp/emb"),
            "reranker": Path("/tmp/rerank"),
        }
        mock_emb.assert_called_once_with("BAAI/bge-small-en-v1.5", cache_dir="/tmp/cache")
        mock_rerank.assert_called_once_with("BAAI/bge-reranker-base", cache_dir="/tmp/cache")
        assert progress_calls == [
            ("embedding", "BAAI/bge-small-en-v1.5"),
            ("reranker", "BAAI/bge-reranker-base"),
        ]


def test_download_profile_models_low_tier() -> None:
    profile = resolve_hardware_profile(HardwareProfileName.LOW)

    with (
        patch(
            "cortex.models.lifecycle.download_embedding_model",
            return_value=Path("/tmp/emb"),
        ) as mock_emb,
        patch("cortex.models.lifecycle.download_reranker_model") as mock_rerank,
    ):
        results = download_profile_models(profile)

        assert results == {"embedding": Path("/tmp/emb")}
        mock_emb.assert_called_once_with("BAAI/bge-small-en-v1.5", cache_dir=None)
        mock_rerank.assert_not_called()


def test_engine_classmethods_integration() -> None:
    with patch(
        "cortex.models.lifecycle.download_embedding_model",
        return_value=Path("/tmp/emb"),
    ) as mock_emb:
        res = EmbeddingEngine.download_model(HardwareProfileName.HIGH)
        assert res == Path("/tmp/emb")
        mock_emb.assert_called_once_with("BAAI/bge-large-en-v1.5", cache_dir=None)

        res_code = EmbeddingEngine.download_model("code")
        assert res_code == Path("/tmp/emb")
        mock_emb.assert_called_with("jinaai/jina-embeddings-v2-base-code", cache_dir=None)

    with patch(
        "cortex.models.lifecycle.download_reranker_model",
        return_value=Path("/tmp/rerank"),
    ) as mock_rerank:
        res_high = RerankerEngine.download_model("high")
        assert res_high == Path("/tmp/rerank")
        mock_rerank.assert_called_once_with("BAAI/bge-reranker-large", cache_dir=None)

        res_code_rerank = RerankerEngine.download_model("code")
        assert res_code_rerank == Path("/tmp/rerank")
        mock_rerank.assert_called_with("jinaai/jina-reranker-v1-turbo-en", cache_dir=None)

        # In low profile, reranker is disabled
        res_low = RerankerEngine.download_model("low")
        assert res_low is None
