"""Code dependency graph, caller tracing, and symbol signature CLI commands."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

import cortex.cli
from cortex.cli.common import console
from cortex.client import ClientMode, CortexRemoteError
from cortex.config.loader import load_config

deps_app = typer.Typer(
    name="deps",
    help="Query code dependencies, callers, and AST signatures.",
    no_args_is_help=True,
)


@deps_app.command(name="trace")
def deps_trace(
    repo: Annotated[
        str,
        typer.Option(
            "--repo",
            "-r",
            help="Repository identifier to trace outgoing dependencies for.",
        ),
    ],
    file: Annotated[
        str | None,
        typer.Option("--file", "-f", help="Target relative file path."),
    ] = None,
    symbol: Annotated[
        str | None,
        typer.Option("--symbol", "-s", help="Containing or called symbol name."),
    ] = None,
    cross_repo_only: Annotated[
        bool,
        typer.Option(
            "--cross-repo-only",
            help="Filter to cross-repository dependencies only.",
        ),
    ] = False,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Maximum dependencies to return."),
    ] = 100,
    remote: Annotated[
        bool | None,
        typer.Option(
            "--remote/--local",
            help="Force querying remote hub or local storage.",
        ),
    ] = None,
    hub_url: Annotated[
        str | None,
        typer.Option("--hub-url", help="Override remote hub URL."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output machine-readable JSON."),
    ] = False,
) -> None:
    """Trace outgoing imports, calls, class heritage, and cross-repo dependencies."""
    cfg = load_config()
    mode: ClientMode = "auto"
    if remote is True:
        mode = "remote"
    elif remote is False:
        mode = "in_process"

    client = cortex.cli.CortexClient(mode=mode, hub_url=hub_url, config=cfg)
    try:
        res = client.get_dependencies(
            repo=repo,
            file_path=file,
            symbol=symbol,
            cross_repo_only=cross_repo_only,
            limit=limit,
        )
    except CortexRemoteError as exc:
        if json_output:
            console.print_json(data={"error": str(exc)})
        else:
            console.print(f"[bold red]Remote hub error:[/bold red] {exc}")
        raise typer.Exit(code=1) from None

    if json_output:
        typer.echo(res.model_dump_json())
        return

    if not res.dependencies:
        console.print(f"[yellow]No dependencies found for repository '{repo}'.[/yellow]")
        return

    table = Table(title=f"Dependencies for '{repo}'", show_header=True)
    table.add_column("Type", style="bold magenta", no_wrap=True)
    table.add_column("Source Location", style="cyan")
    table.add_column("Source Symbol", style="green")
    table.add_column("Target (Module :: Symbol)", style="yellow")
    table.add_column("Target Repo", style="bold blue", no_wrap=True)

    for dep in res.dependencies:
        target_str = dep.target_module
        if dep.target_symbol:
            target_str += f" :: {dep.target_symbol}"
        loc_str = f"{dep.source_file}:{dep.line_number}"
        table.add_row(
            dep.edge_type.value,
            loc_str,
            dep.source_symbol or "-",
            target_str,
            dep.target_repo or "-",
        )

    console.print(table)

    if res.cross_repo_links:
        console.print(
            f"\n[bold green]Found {len(res.cross_repo_links)} Cross-Repository "
            "Architectural Bridge(s):[/bold green]"
        )
        link_tbl = Table(show_header=True)
        link_tbl.add_column("Source", style="cyan")
        link_tbl.add_column("Target Repo", style="bold blue")
        link_tbl.add_column("Edge", style="magenta")
        link_tbl.add_column("Symbol / Detail", style="yellow")
        for link in res.cross_repo_links:
            link_tbl.add_row(
                f"{link.source_file}",
                link.target_repo,
                link.edge_type.value,
                link.detail or link.symbol,
            )
        console.print(link_tbl)


@deps_app.command(name="callers")
def deps_callers(
    symbol: Annotated[
        str,
        typer.Option(
            "--symbol",
            "-s",
            help="Target function, method, or symbol to trace callers for.",
        ),
    ],
    module: Annotated[
        str | None,
        typer.Option("--module", "-m", help="Target module or package name."),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Maximum callers/dependents to return."),
    ] = 100,
    remote: Annotated[
        bool | None,
        typer.Option(
            "--remote/--local",
            help="Force querying remote hub or local storage.",
        ),
    ] = None,
    hub_url: Annotated[
        str | None,
        typer.Option("--hub-url", help="Override remote hub URL."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output machine-readable JSON."),
    ] = False,
) -> None:
    """Find incoming callers, importers, and dependents for a symbol or module."""
    cfg = load_config()
    mode: ClientMode = "auto"
    if remote is True:
        mode = "remote"
    elif remote is False:
        mode = "in_process"

    client = cortex.cli.CortexClient(mode=mode, hub_url=hub_url, config=cfg)
    try:
        res = client.get_dependents(symbol=symbol, module=module, limit=limit)
    except CortexRemoteError as exc:
        if json_output:
            console.print_json(data={"error": str(exc)})
        else:
            console.print(f"[bold red]Remote hub error:[/bold red] {exc}")
        raise typer.Exit(code=1) from None

    if json_output:
        typer.echo(res.model_dump_json())
        return

    if not res.dependents:
        console.print(f"[yellow]No callers or dependents found for symbol '{symbol}'.[/yellow]")
        return

    table = Table(title=f"Callers and Dependents for '{symbol}'", show_header=True)
    table.add_column("Edge Type", style="bold magenta", no_wrap=True)
    table.add_column("Caller Repo", style="bold cyan", no_wrap=True)
    table.add_column("Location", style="cyan")
    table.add_column("Caller Symbol", style="green")
    table.add_column("Statement", style="dim")

    for dep in res.dependents:
        table.add_row(
            dep.edge_type.value,
            dep.source_repo,
            f"{dep.source_file}:{dep.line_number}",
            dep.source_symbol or "-",
            dep.raw_statement or "-",
        )

    console.print(table)


@deps_app.command(name="signatures")
def deps_signatures(
    query: Annotated[
        str,
        typer.Argument(help="Identifier or keyword substring to search."),
    ],
    repo: Annotated[
        str | None,
        typer.Option("--repo", "-r", help="Filter by repository identifier."),
    ] = None,
    kind: Annotated[
        str | None,
        typer.Option(
            "--kind",
            "-k",
            help="Filter by symbol kind (function, method, class, struct, interface, etc.).",
        ),
    ] = None,
    language: Annotated[
        str | None,
        typer.Option("--language", help="Filter by programming language (python, typescript, go)."),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Maximum signatures to return."),
    ] = 50,
    remote: Annotated[
        bool | None,
        typer.Option(
            "--remote/--local",
            help="Force querying remote hub or local storage.",
        ),
    ] = None,
    hub_url: Annotated[
        str | None,
        typer.Option("--hub-url", help="Override remote hub URL."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output machine-readable JSON."),
    ] = False,
) -> None:
    """Lookup AST code contracts and symbol signatures."""
    cfg = load_config()
    mode: ClientMode = "auto"
    if remote is True:
        mode = "remote"
    elif remote is False:
        mode = "in_process"

    client = cortex.cli.CortexClient(mode=mode, hub_url=hub_url, config=cfg)
    try:
        res = client.get_signatures(
            query=query,
            repo=repo,
            kind=kind,
            language=language,
            limit=limit,
        )
    except CortexRemoteError as exc:
        if json_output:
            console.print_json(data={"error": str(exc)})
        else:
            console.print(f"[bold red]Remote hub error:[/bold red] {exc}")
        raise typer.Exit(code=1) from None

    if json_output:
        typer.echo(res.model_dump_json())
        return

    if not res.signatures:
        console.print(f"[yellow]No signatures found matching query '{query}'.[/yellow]")
        return

    table = Table(title=f"Code Signatures for '{query}'", show_header=True)
    table.add_column("Repo", style="bold cyan", no_wrap=True)
    table.add_column("Lang", style="blue", no_wrap=True)
    table.add_column("Kind", style="magenta", no_wrap=True)
    table.add_column("Identifier", style="bold green")
    table.add_column("Signature", style="yellow")
    table.add_column("Location", style="dim", no_wrap=True)

    for sig in res.signatures:
        table.add_row(
            sig.repo,
            sig.language,
            sig.kind,
            sig.identifier,
            sig.signature,
            f"{sig.file_path}:{sig.line_start}-{sig.line_end}",
        )

    console.print(table)
