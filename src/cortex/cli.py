"""CLI entrypoint for agent-cortex."""

import typer
from rich.console import Console

app = typer.Typer(
    name="cortex",
    help="Cross-repository semantic memory and portfolio knowledge engine.",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def cortex_callback() -> None:
    """agent-cortex: Cross-repository semantic memory and portfolio knowledge engine."""


@app.command()
def version() -> None:
    """Print the version of agent-cortex."""
    from cortex import __version__

    console.print(f"[bold cyan]agent-cortex[/bold cyan] version [green]{__version__}[/green]")


def main() -> None:
    """Main CLI execution entrypoint."""
    app()


if __name__ == "__main__":
    main()
