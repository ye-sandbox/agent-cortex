"""Hermetic CLI tests for remote fail-fast and terminal diagnostics."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
from typer.testing import CliRunner

from cortex.cli import app

runner = CliRunner()
_REAL_HTTPX_CLIENT = httpx.Client


def test_cli_search_remote_connection_failure_diagnostics() -> None:
    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused by test mock")

    def mock_client_factory(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        return _REAL_HTTPX_CLIENT(*args, **kwargs)

    with patch("cortex.client.httpx.Client", side_effect=mock_client_factory):
        result = runner.invoke(
            app,
            ["search", "authentication flow", "--remote", "--hub-url", "http://offline-hub:8000"],
        )

    assert result.exit_code == 1
    assert "Remote Hub Connection Failed" in result.stdout
    assert "http://offline-hub:8000" in result.stdout
    assert "--local" in result.stdout
    assert "cortex serve" in result.stdout


def test_cli_search_remote_json_streaming_connection_failure() -> None:
    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Network timeout during streaming handshake")

    def mock_client_factory(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        return _REAL_HTTPX_CLIENT(*args, **kwargs)

    with patch("cortex.client.httpx.Client", side_effect=mock_client_factory):
        result = runner.invoke(
            app,
            [
                "search",
                "authentication flow",
                "--json",
                "--remote",
                "--hub-url",
                "http://offline-hub:8000",
            ],
        )

    assert result.exit_code == 1
    assert "Remote Hub Connection Failed" in result.stdout
    assert "http://offline-hub:8000" in result.stdout
    assert "--local" in result.stdout


def test_cli_search_remote_timeout_diagnostics() -> None:
    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Read timed out after 30.0s")

    def mock_client_factory(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        return _REAL_HTTPX_CLIENT(*args, **kwargs)

    with patch("cortex.client.httpx.Client", side_effect=mock_client_factory):
        result = runner.invoke(
            app,
            ["search", "contract query", "--remote", "--hub-url", "http://slow-hub:8000"],
        )

    assert result.exit_code == 1
    assert "Remote Hub Connection Failed" in result.stdout
    assert "http://slow-hub:8000" in result.stdout
    assert "Read timed out" in result.stdout
    assert "--local" in result.stdout
