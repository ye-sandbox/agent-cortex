"""Transitive blast-radius simulation and caller impact tracing CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

import cortex.cli
from cortex.cli.common import console
from cortex.client import ClientMode
from cortex.config.loader import load_config
from cortex.models.impact import BlastRadiusSeverity


def _format_risk_badge(sev: BlastRadiusSeverity) -> str:
    """Format Rich ANSI badge for BlastRadiusSeverity."""
    match sev:
        case BlastRadiusSeverity.CRITICAL:
            return "[bold white on red] CRITICAL [/bold white on red]"
        case BlastRadiusSeverity.HIGH:
            return "[bold black on yellow] HIGH [/bold black on yellow]"
        case BlastRadiusSeverity.MEDIUM:
            return "[bold blue]MEDIUM[/bold blue]"
        case BlastRadiusSeverity.LOW:
            return "[dim cyan]LOW[/dim cyan]"
        case BlastRadiusSeverity.MINIMAL:
            return "[dim green]MINIMAL[/dim green]"


impact_app = typer.Typer(
    name="impact",
    help="Simulate change blast radius and trace transitive caller impact across repositories.",
    no_args_is_help=True,
)


@impact_app.command(name="simulate")
def impact_simulate(
    repo: Annotated[
        str,
        typer.Argument(help="Target repository identifier to evaluate."),
    ],
    symbol: Annotated[
        str | None,
        typer.Option("--symbol", "-s", help="Specific target symbol or signature identifier."),
    ] = None,
    file_path: Annotated[
        str | None,
        typer.Option("--file", "-f", help="Specific target file path within repository."),
    ] = None,
    change_kind: Annotated[
        str,
        typer.Option(
            "--change-kind",
            "-k",
            help="Proposed change kind: MODIFIED, REMOVED, ADDED, DEPRECATED.",
        ),
    ] = "MODIFIED",
    max_depth: Annotated[
        int,
        typer.Option(
            "--max-depth",
            "-d",
            help="Maximum transitive caller hop search depth.",
        ),
    ] = 5,
    fail_on_risk: Annotated[
        bool,
        typer.Option(
            "--fail-on-risk",
            help="Exit with code 1 if risk is CRITICAL/HIGH (useful for CI/CD gates).",
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
    """Simulate change blast radius and synthesize AI agent planning advisories."""
    cfg = load_config(config_path)
    mode: ClientMode = "remote" if remote else "auto"

    with cortex.cli.CortexClient(mode=mode, hub_url=hub_url, api_key=api_key, config=cfg) as client:
        try:
            report = client.simulate_blast_radius(
                repo=repo,
                symbol=symbol,
                file_path=file_path,
                change_kind=change_kind,
                max_depth=max_depth,
            )
        except Exception as exc:
            console.print(f"[bold red]Failed to simulate blast radius:[/bold red] {exc}")
            raise typer.Exit(code=1) from exc

    if json_output:
        console.print(report.model_dump_json(indent=2))
        if fail_on_risk and report.is_breaking:
            raise typer.Exit(code=1)
        return

    # Visual Output
    target_desc = f"[bold cyan]{report.target_repo}[/bold cyan]"
    if report.target_file:
        target_desc += f" : {report.target_file}"
    if report.target_symbol:
        target_desc += f" :: [bold yellow]{report.target_symbol}[/bold yellow]"

    console.print(
        Panel(
            f"Target: {target_desc}\n"
            f"Proposed Change: [magenta]{report.change_kind}[/magenta] | "
            f"Max Traversal Depth: [cyan]{report.max_depth}[/cyan]\n"
            f"Risk Score: [bold]{report.risk_score:.1f}[/bold]/100.0  "
            f"Risk Level: {_format_risk_badge(report.risk_level)}",
            title="Blast-Radius Simulation",
            expand=False,
        )
    )

    if not report.impacted_nodes:
        console.print(
            "\n[bold green]✓ Zero incoming callers detected within search depth. "
            "Isolated blast radius.[/bold green]"
        )
        return

    # Impacted Components Table
    table = Table(title="Impacted Downstream Components", show_header=True)
    table.add_column("Hop", justify="center", no_wrap=True)
    table.add_column("Direct?", justify="center", no_wrap=True)
    table.add_column("Repo", style="bold cyan", no_wrap=True)
    table.add_column("File Path", style="blue")
    table.add_column("Symbol / Caller Scope", style="bold")
    table.add_column("Call Paths", justify="right", style="yellow")

    for node in report.impacted_nodes:
        direct_badge = "[green]Yes[/green]" if node.direct else "[dim]No[/dim]"
        is_cross = "[red]*[/red] " if node.repo != report.target_repo else ""
        table.add_row(
            str(node.depth),
            direct_badge,
            f"{is_cross}{node.repo}",
            node.file_path,
            node.symbol,
            str(node.caller_count),
        )

    console.print(table)

    # Planning Advisories
    if report.advisories:
        adv_table = Table(title="AI Agent Planning Advisories", show_header=True)
        adv_table.add_column("Sev", justify="center", no_wrap=True)
        adv_table.add_column("Category", style="magenta", no_wrap=True)
        adv_table.add_column("Diagnostic Message", style="yellow")
        adv_table.add_column("Recommended Action", style="bold green")

        for adv in report.advisories:
            adv_table.add_row(
                _format_risk_badge(adv.severity),
                adv.category,
                adv.message,
                adv.recommended_action,
            )
        console.print(adv_table)

    # Recommended Update Order
    if report.recommended_update_order:
        staging_text = "\n".join(
            f"{idx}. {item}" for idx, item in enumerate(report.recommended_update_order, 1)
        )
        console.print(
            Panel(
                staging_text,
                title="Recommended Staging Sequence (Leaves First)",
                expand=False,
            )
        )

    if fail_on_risk and report.is_breaking:
        console.print(
            f"\n[bold red]Error: Blast radius risk is {report.risk_level.value} "
            f"(Score: {report.risk_score:.1f}) exceeding risk threshold![/bold red]"
        )
        raise typer.Exit(code=1)


@impact_app.command(name="trace")
def impact_trace(
    repo: Annotated[
        str,
        typer.Argument(help="Target repository identifier to evaluate."),
    ],
    symbol: Annotated[
        str | None,
        typer.Option("--symbol", "-s", help="Specific target symbol or signature identifier."),
    ] = None,
    file_path: Annotated[
        str | None,
        typer.Option("--file", "-f", help="Specific target file path within repository."),
    ] = None,
    max_depth: Annotated[
        int,
        typer.Option(
            "--max-depth",
            "-d",
            help="Maximum transitive caller hop search depth.",
        ),
    ] = 5,
    tree_view: Annotated[
        bool,
        typer.Option("--tree", "-t", help="Render caller chains as a visual hierarchical tree."),
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
    """Trace incoming transitive caller chains across portfolio repositories."""
    cfg = load_config(config_path)
    mode: ClientMode = "remote" if remote else "auto"

    with cortex.cli.CortexClient(mode=mode, hub_url=hub_url, api_key=api_key, config=cfg) as client:
        try:
            chains, nodes, cycles = client.trace_impact(
                repo=repo,
                symbol=symbol,
                file_path=file_path,
                max_depth=max_depth,
            )
        except Exception as exc:
            console.print(f"[bold red]Failed to trace impact:[/bold red] {exc}")
            raise typer.Exit(code=1) from exc

    if json_output:
        import json

        data = {
            "target_repo": repo,
            "symbol": symbol,
            "file_path": file_path,
            "total_chains": len(chains),
            "caller_chains": [c.model_dump(mode="json") for c in chains],
            "total_impacted_nodes": len(nodes),
            "impacted_nodes": [n.model_dump(mode="json") for n in nodes],
            "cycles_detected": cycles,
        }
        console.print(json.dumps(data, indent=2))
        return

    if not chains:
        console.print(
            f"[bold green]✓ Zero incoming caller chains found for '{repo}'"
            + (f" :: '{symbol}'" if symbol else "")
            + ".[/bold green]"
        )
        return

    target_label = f"[bold cyan]{repo}[/bold cyan]"
    if symbol:
        target_label += f" :: [bold yellow]{symbol}[/bold yellow]"

    if tree_view:
        root_tree = Tree(f"Target: {target_label}")
        # Build hierarchy from caller chains
        for chain in chains:
            curr = root_tree
            for hop in chain.hops:
                cross = "[red](cross-repo)[/red] " if hop.repo != repo else ""
                hop_text = (
                    f"[{hop.depth}] {cross}[cyan]{hop.repo}[/cyan]:"
                    f"[blue]{hop.file_path}[/blue]:[bold]{hop.symbol}[/bold]:{hop.line_number} "
                    f"([magenta]{hop.edge_type.value}[/magenta])"
                )
                curr = curr.add(hop_text)
        console.print(root_tree)
    else:
        table = Table(title=f"Transitive Caller Chains for {target_label}", show_header=True)
        table.add_column("Hops", justify="center", no_wrap=True)
        table.add_column("Cross-Repo?", justify="center", no_wrap=True)
        table.add_column("Caller Path", style="bold")

        for chain in chains:
            cross_badge = "[red]Yes[/red]" if chain.cross_repo else "[dim]No[/dim]"
            table.add_row(str(chain.depth), cross_badge, chain.path_str)

        console.print(table)

    summary = (
        f"Total Chains: [bold]{len(chains)}[/bold] | "
        f"Impacted Nodes: [bold cyan]{len(nodes)}[/bold cyan] | "
        f"Cycles Detected: [bold red]{len(cycles)}[/bold red]"
    )
    console.print(Panel(summary, title="Impact Trace Summary", expand=False))
