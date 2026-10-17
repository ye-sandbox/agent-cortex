from typer.testing import CliRunner

from cortex import __version__
from cortex.cli import app
from cortex.mcp_server import cortex_version

runner = CliRunner()


def test_baseline_environment() -> None:
    """Verifies that the test execution framework is functional."""
    assert 1 + 1 == 2


def test_core_dependencies_importable() -> None:
    """Verifies that core ML and runtime dependencies are correctly packaged and importable."""
    import fastembed
    import lancedb
    import mcp
    import pydantic
    import rich
    import typer
    import yaml

    assert fastembed.__version__ is not None
    assert lancedb.__version__ is not None
    assert mcp.__name__ == "mcp"
    assert pydantic.__version__ is not None
    assert rich.__name__ == "rich"
    assert typer.__name__ == "typer"
    assert yaml.__name__ == "yaml"


def test_cli_version_command() -> None:
    """Verifies that the cortex CLI entrypoint executes and outputs version."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_mcp_version_tool() -> None:
    """Verifies that the MCP server exposes the version tool."""
    version_str = cortex_version()
    assert __version__ in version_str
