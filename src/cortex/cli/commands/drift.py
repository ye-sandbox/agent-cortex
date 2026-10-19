"""Contract drift and breaking change detection CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

import cortex.cli
from cortex.cli.common import _format_severity_badge, console
from cortex.client import ClientMode
from cortex.config.loader import load_config

drift_app = typer.Typer(
    name="drift",
    help="Detect and audit cross-repository architectural contract drift and breaking changes.",
    no_args_is_help=True,
)


@drift_app.command(name="audit")
@drift_app.command(name="check", hidden=True)
def drift_audit(
    repo: Annotated[
        str | None,
        typer.Argument(help="Optional target repository name (audits all configured if omitted)."),
    ] = None,
    breaking_only: Annotated[
        bool,
        typer.Option(
            "--breaking-only",
            "-b",
            help="Filter for breaking contract drift (CRITICAL and HIGH) only.",
        ),
    ] = False,
    cross_repo_only: Annotated[
        bool,
        typer.Option(
            "--cross-repo-only",
            help="Filter for contract drift that impacts downstream portfolio repositories.",
        ),
    ] = False,
    fail_on_breaking: Annotated[
        bool,
        typer.Option(
            "--fail-on-breaking",
            help="Exit with code 1 if breaking contract changes are detected (useful for CI/CD).",
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
    """Audit architectural contract drift and breaking changes across portfolio repositories."""
    cfg = load_config(config_path)
    mode: ClientMode = "remote" if remote else "auto"
    with cortex.cli.CortexClient(mode=mode, hub_url=hub_url, api_key=api_key, config=cfg) as client:
        try:
            report = client.get_contract_drift(
                repo=repo,
                breaking_only=breaking_only,
                cross_repo_only=cross_repo_only,
            )
        except Exception as exc:
            console.print(f"[bold red]Failed to inspect contract drift:[/bold red] {exc}")
            raise typer.Exit(code=1) from exc

    if json_output:
        console.print(report.model_dump_json(indent=2))
        if fail_on_breaking and report.breaking_count > 0:
            raise typer.Exit(code=1)
        return

    if not report.alerts:
        scope_str = f" for repository '{repo}'" if repo else " across portfolio"
        console.print(
            f"[bold green]✓ No architectural contract drift detected{scope_str}.[/bold green]"
        )
        return

    target_title = (
        f"Contract Drift Audit for '{repo}'" if repo else "Portfolio Contract Drift Audit"
    )
    table = Table(title=target_title, show_header=True)
    table.add_column("Sev", justify="center", no_wrap=True)
    table.add_column("Repo", style="bold cyan", no_wrap=True)
    table.add_column("Contract", style="magenta", no_wrap=True)
    table.add_column("Change", style="blue", no_wrap=True)
    table.add_column("Identifier", style="bold")
    table.add_column("Summary", style="yellow")
    table.add_column("Downstream Impact", style="red", no_wrap=True)

    for alert in report.alerts:
        impact = ", ".join(alert.impacted_repos) if alert.impacted_repos else "-"
        table.add_row(
            _format_severity_badge(alert.severity),
            alert.repo,
            alert.contract_type.value,
            alert.change_kind.value,
            alert.identifier,
            alert.summary,
            impact,
        )

    console.print(table)
    summary_line = (
        f"Total Alerts: [bold]{report.total_alerts}[/bold] | "
        f"Breaking: [bold red]{report.breaking_count}[/bold red] | "
        f"Warnings: [bold yellow]{report.warning_count}[/bold yellow] | "
        f"Info: [dim]{report.info_count}[/dim]"
    )
    console.print(Panel(summary_line, title="Audit Summary", expand=False))

    if fail_on_breaking and report.breaking_count > 0:
        console.print(
            f"\n[bold red]Error: {report.breaking_count} breaking architectural contract "
            "change(s) detected![/bold red]"
        )
        raise typer.Exit(code=1)


@drift_app.command(name="alerts")
def drift_alerts(
    repo: Annotated[
        str | None,
        typer.Option("--repo", "-r", help="Target repository name."),
    ] = None,
    breaking_only: Annotated[
        bool,
        typer.Option("--breaking-only", "-b", help="Filter for breaking contract drift only."),
    ] = True,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output machine-readable JSON."),
    ] = False,
    config_path: Annotated[
        Path | None,
        typer.Option("--config-path", "-c", help="Custom configuration path."),
    ] = None,
) -> None:
    """List active breaking architectural contract alerts."""
    drift_audit(
        repo=repo,
        breaking_only=breaking_only,
        cross_repo_only=False,
        fail_on_breaking=False,
        json_output=json_output,
        config_path=config_path,
    )
