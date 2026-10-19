"""Portfolio topology, matrix analysis, and cycle detection CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

import cortex.cli
from cortex.cli.common import console
from cortex.client import ClientMode
from cortex.config.loader import load_config
from cortex.models.topology import PortfolioTopologyGraph

topology_app = typer.Typer(
    name="topology",
    help=(
        "Synthesize and visualize cross-repository dependency topology matrices "
        "and architectural graphs."
    ),
    no_args_is_help=True,
)


@topology_app.command(name="matrix")
def topology_matrix(
    min_weight: Annotated[
        int,
        typer.Option("--min-weight", "-w", help="Minimum dependency references between repos."),
    ] = 0,
    highlight_cycles: Annotated[
        bool,
        typer.Option(
            "--highlight-cycles/--no-highlight-cycles",
            help="Highlight circular dependency paths.",
        ),
    ] = True,
    remote: Annotated[
        bool,
        typer.Option("--remote", help="Force querying remote daemon instead of local LanceDB."),
    ] = False,
    hub_url: Annotated[
        str | None,
        typer.Option("--hub-url", help="Override remote hub URL."),
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", help="Override remote Bearer token."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output machine-readable JSON."),
    ] = False,
    config_path: Annotated[
        Path | None,
        typer.Option("--config-path", "-c", help="Custom configuration path."),
    ] = None,
) -> None:
    """Synthesize cross-repository dependency NxN matrix and architectural coupling metrics."""
    cfg = load_config(config_path)
    mode: ClientMode = "remote" if remote else "auto"
    with cortex.cli.CortexClient(mode=mode, hub_url=hub_url, api_key=api_key, config=cfg) as client:
        try:
            matrix = client.get_dependency_matrix(min_weight=min_weight)
        except Exception as exc:
            console.print(f"[bold red]Failed to inspect dependency matrix:[/bold red] {exc}")
            raise typer.Exit(code=1) from exc

    if json_output:
        console.print_json(data=matrix.model_dump(mode="json"))
        return

    if not matrix.repos:
        console.print("[dim]No portfolio repositories or dependencies indexed.[/dim]")
        return

    cycle_repos: set[str] = set()
    if highlight_cycles:
        for c in matrix.cycles:
            cycle_repos.update(c.path)

    table = Table(
        title=f"Cross-Repository Dependency Matrix (min_weight >= {min_weight})",
        show_header=True,
        header_style="bold cyan",
        title_style="bold magenta",
    )
    table.add_column("Source Repository", style="bold white")
    for r in matrix.repos:
        table.add_column(r, justify="center", style="dim")
    table.add_column("Ca", justify="right", style="green")
    table.add_column("Ce", justify="right", style="cyan")
    table.add_column("Instability (I)", justify="right", style="yellow")

    for row in matrix.rows:
        source_display = row.source_repo
        if row.source_repo in cycle_repos:
            source_display = f"[bold red]! {row.source_repo}[/bold red]"

        cells: list[str] = [source_display]
        for tgt in matrix.repos:
            cnt = row.targets.get(tgt, 0)
            if row.source_repo == tgt:
                cells.append("[dim]—[/dim]")
            elif cnt > 0:
                cells.append(f"[bold green]{cnt}[/bold green]")
            else:
                cells.append("[dim]0[/dim]")

        cells.append(str(row.afferent_coupling))
        cells.append(str(row.efferent_coupling))
        cells.append(f"{row.instability:.2f}")
        table.add_row(*cells)

    console.print(table)

    summary = matrix.summary
    total_edges = summary.get("total_cross_repo_edges", 0)
    total_refs = summary.get("total_cross_repo_references", 0)
    summary_lines = [
        f"• Total Repositories: [bold white]{summary.get('total_repositories', 0)}[/bold white]",
        f"• Cross-Repo Edges: [bold cyan]{total_edges}[/bold cyan] ([dim]{total_refs} refs[/dim])",
        f"• Graph Density: [bold yellow]{summary.get('density', 0.0):.4f}[/bold yellow]",
    ]
    if summary.get("most_depended_repository"):
        hub_name = summary.get("most_depended_repository")
        summary_lines.append(f"• Foundational Hub: [bold green]{hub_name}[/bold green]")
    if summary.get("most_dependent_repository"):
        consumer_name = summary.get("most_dependent_repository")
        summary_lines.append(f"• Top Consumer: [bold cyan]{consumer_name}[/bold cyan]")

    if matrix.cycles:
        summary_lines.append(
            f"\n[bold red]⚠️ Circular Dependencies Detected ({len(matrix.cycles)}):[/bold red]"
        )
        for c in matrix.cycles:
            path_str = " -> ".join(c.path)
            summary_lines.append(f"  [red]• {path_str}[/red] ({c.length} hops)")

    console.print(
        Panel("\n".join(summary_lines), title="Portfolio Topology Summary", border_style="cyan")
    )


@topology_app.command(name="graph")
@topology_app.command(name="export", hidden=True)
def topology_graph(
    export_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Export format: mermaid, dot, cytoscape, json."),
    ] = "mermaid",
    direction: Annotated[
        str,
        typer.Option("--direction", "-d", help="Graph layout direction for Mermaid: LR or TD."),
    ] = "LR",
    min_weight: Annotated[
        int,
        typer.Option("--min-weight", "-w", help="Minimum dependency references between repos."),
    ] = 1,
    include_internal: Annotated[
        bool,
        typer.Option("--include-internal", help="Include intra-repository dependencies."),
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write export to destination file path."),
    ] = None,
    remote: Annotated[
        bool,
        typer.Option("--remote", help="Force querying remote daemon instead of local LanceDB."),
    ] = False,
    hub_url: Annotated[
        str | None,
        typer.Option("--hub-url", help="Override remote hub URL."),
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", help="Override remote Bearer token."),
    ] = None,
    config_path: Annotated[
        Path | None,
        typer.Option("--config-path", "-c", help="Custom configuration path."),
    ] = None,
) -> None:
    """Generate and export portfolio topology diagrams in Mermaid, DOT, Cytoscape, or JSON."""
    cfg = load_config(config_path)
    mode: ClientMode = "remote" if remote else "auto"
    with cortex.cli.CortexClient(mode=mode, hub_url=hub_url, api_key=api_key, config=cfg) as client:
        try:
            result = client.get_portfolio_topology(
                format=export_format,
                direction=direction,
                include_internal=include_internal,
                min_weight=min_weight,
            )
        except Exception as exc:
            console.print(f"[bold red]Failed to export topology graph:[/bold red] {exc}")
            raise typer.Exit(code=1) from exc

    if isinstance(result, PortfolioTopologyGraph):
        content_str = json.dumps(result.model_dump(mode="json"), indent=2)
    elif isinstance(result, dict):
        content_str = json.dumps(result, indent=2)
    else:
        content_str = str(result)

    if output:
        out_path = output.expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content_str, encoding="utf-8")
        console.print(
            f"[bold green]Successfully exported topology graph to:[/bold green] {out_path}"
        )
    else:
        if export_format.lower() in ("json", "cytoscape"):
            console.print_json(content_str)
        else:
            console.print(content_str)


@topology_app.command(name="cycles")
def topology_cycles(
    min_weight: Annotated[
        int,
        typer.Option("--min-weight", "-w", help="Minimum dependency references."),
    ] = 1,
    fail_on_cycles: Annotated[
        bool,
        typer.Option(
            "--fail-on-cycles",
            help="Exit with code 1 if any cycles are detected (useful for CI/CD gates).",
        ),
    ] = False,
    remote: Annotated[
        bool,
        typer.Option("--remote", help="Force querying remote daemon instead of local LanceDB."),
    ] = False,
    hub_url: Annotated[
        str | None,
        typer.Option("--hub-url", help="Override remote hub URL."),
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", help="Override remote Bearer token."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output machine-readable JSON."),
    ] = False,
    config_path: Annotated[
        Path | None,
        typer.Option("--config-path", "-c", help="Custom configuration path."),
    ] = None,
) -> None:
    """Detect and report circular architectural dependencies across portfolio repositories."""
    cfg = load_config(config_path)
    mode: ClientMode = "remote" if remote else "auto"
    with cortex.cli.CortexClient(mode=mode, hub_url=hub_url, api_key=api_key, config=cfg) as client:
        try:
            cycles = client.get_topology_cycles(min_weight=min_weight)
        except Exception as exc:
            console.print(f"[bold red]Failed to inspect cycles:[/bold red] {exc}")
            raise typer.Exit(code=1) from exc

    if json_output:
        console.print_json(data=[c.model_dump(mode="json") for c in cycles])
        if fail_on_cycles and cycles:
            raise typer.Exit(code=1)
        return

    if not cycles:
        console.print(
            "[bold green]Zero circular dependencies detected across "
            "portfolio repositories.[/bold green]"
        )
        return

    console.print(
        f"[bold red]Detected {len(cycles)} circular architectural dependency paths:[/bold red]\n"
    )
    for i, c in enumerate(cycles, 1):
        path_str = " -> ".join(f"[bold red]{r}[/bold red]" for r in c.path)
        console.print(f"  {i}. {path_str} [dim]({c.length} hops)[/dim]")

    if fail_on_cycles:
        raise typer.Exit(code=1)
