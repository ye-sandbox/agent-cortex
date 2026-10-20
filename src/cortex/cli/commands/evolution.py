"""Contract evolution timeline and changelog synthesis CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import typer
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

import cortex.cli
from cortex.cli.common import _format_severity_badge, console
from cortex.client import ClientMode
from cortex.config.loader import load_config
from cortex.ingestion.discovery import resolve_sync_sources
from cortex.retrieval.evolution import ContractEvolutionEngine

history_app = typer.Typer(
    name="history",
    help="Inspect and scan git repository history for architectural contract mutations.",
    no_args_is_help=True,
)


def timeline_cmd(
    repo: Annotated[
        str | None,
        typer.Argument(help="Optional target repository name (all repos if omitted)."),
    ] = None,
    contract_type: Annotated[
        str | None,
        typer.Option(
            "--type",
            "-t",
            help="Filter by contract type (openapi, compose, code_signature).",
        ),
    ] = None,
    change_kind: Annotated[
        str | None,
        typer.Option(
            "--kind",
            "-k",
            help="Filter by change kind (added, modified, deprecated, removed).",
        ),
    ] = None,
    breaking_only: Annotated[
        bool,
        typer.Option(
            "--breaking-only",
            "-b",
            help="Filter for breaking contract changes (CRITICAL and HIGH) only.",
        ),
    ] = False,
    since: Annotated[
        str | None,
        typer.Option("--since", help="Filter events starting from ISO timestamp / date."),
    ] = None,
    until: Annotated[
        str | None,
        typer.Option("--until", help="Filter events up to ISO timestamp / date."),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", "-n", help="Maximum number of events to return."),
    ] = 50,
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
    """Display chronological history of architectural contract mutations across repositories."""
    cfg = load_config(config_path)
    mode: ClientMode = "remote" if remote else "auto"

    with cortex.cli.CortexClient(mode=mode, hub_url=hub_url, api_key=api_key, config=cfg) as client:
        try:
            timeline = client.get_contract_timeline(
                repo=repo,
                contract_type=contract_type,
                change_kind=change_kind,
                breaking_only=breaking_only,
                since_date=since,
                until_date=until,
                limit=limit,
            )
        except Exception as exc:
            console.print(f"[bold red]Failed to retrieve contract timeline:[/bold red] {exc}")
            raise typer.Exit(code=1) from exc

    if json_output:
        console.print(timeline.model_dump_json(indent=2))
        return

    if not timeline.events:
        target_str = f" for '{repo}'" if repo else " across portfolio"
        console.print(f"[bold green]✓ No contract evolution events found{target_str}.[/bold green]")
        return

    # Render summary header
    title = f"Architectural Contract Timeline — {repo}" if repo else "Portfolio Contract Timeline"
    summary_text = (
        f"[bold]Total Mutations:[/bold] {timeline.total_events}  |  "
        f"[bold red]Breaking:[/bold red] {timeline.breaking_count}  |  "
        f"[bold yellow]Warnings:[/bold yellow] {timeline.warning_count}  |  "
        f"[bold blue]Info:[/bold blue] {timeline.info_count}"
    )
    console.print(Panel(summary_text, title=f"[bold cyan]{title}[/bold cyan]"))

    table = Table(box=None, header_style="bold magenta", expand=True)
    table.add_column("Date", style="dim", width=16)
    table.add_column("Repository", style="bold cyan", width=18)
    table.add_column("Severity", width=10)
    table.add_column("Contract", style="yellow")
    table.add_column("Kind", width=10)
    table.add_column("Summary")

    for evt in timeline.events:
        dt_str = evt.commit_date[:16].replace("T", " ")
        badge = _format_severity_badge(evt.severity)
        contract_desc = f"{evt.contract_type.value}: {evt.identifier}"
        table.add_row(
            dt_str,
            f"{evt.repo} @ {evt.commit_sha[:7]}",
            badge,
            contract_desc,
            evt.change_kind.value,
            evt.summary,
        )

    console.print(table)


def changelog_cmd(
    repo: Annotated[
        str | None,
        typer.Argument(help="Optional target repository name (portfolio-wide if omitted)."),
    ] = None,
    group_by: Annotated[
        str,
        typer.Option(
            "--group-by",
            "-g",
            help="Grouping strategy for releases: release (default), date, or repo.",
        ),
    ] = "release",
    breaking_only: Annotated[
        bool,
        typer.Option(
            "--breaking-only",
            "-b",
            help="Include only breaking changes (CRITICAL and HIGH).",
        ),
    ] = False,
    format_type: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Output format: rich (terminal), markdown (plain md), or json.",
        ),
    ] = "rich",
    output_file: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write generated changelog to destination file."),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", "-n", help="Maximum number of events to process."),
    ] = 200,
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
    """Synthesize structured architectural changelog from recorded contract mutations."""
    cfg = load_config(config_path)
    mode: ClientMode = "remote" if remote else "auto"

    group_strategy: Literal["release", "date", "repo"] = (
        "date" if group_by == "date" else ("repo" if group_by == "repo" else "release")
    )

    with cortex.cli.CortexClient(mode=mode, hub_url=hub_url, api_key=api_key, config=cfg) as client:
        try:
            changelog = client.synthesize_changelog(
                repo=repo,
                group_by=group_strategy,
                breaking_only=breaking_only,
                limit=limit,
            )
        except Exception as exc:
            console.print(
                f"[bold red]Failed to synthesize architectural changelog:[/bold red] {exc}"
            )
            raise typer.Exit(code=1) from exc

    if json_output or format_type == "json":
        console.print(changelog.model_dump_json(indent=2))
        return

    md_content = changelog.to_markdown()

    if output_file is not None:
        out_p = output_file.expanduser().resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(md_content, encoding="utf-8")
        console.print(f"[bold green]✓ Changelog successfully written to:[/bold green] {out_p}")
        return

    if format_type in ("markdown", "md"):
        console.print(md_content, end="")
        return

    # Render formatted markdown in rich terminal
    console.print(Markdown(md_content))


@history_app.command(name="scan")
def history_scan_cmd(
    repo: Annotated[
        str | None,
        typer.Argument(help="Optional target repository name (all repos if omitted)."),
    ] = None,
    max_commits: Annotated[
        int,
        typer.Option("--max-commits", "-m", help="Maximum commits per repository to inspect."),
    ] = 20,
    since_commit: Annotated[
        str | None,
        typer.Option("--since-commit", help="Commit SHA from which to start scanning history."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output machine-readable JSON summary."),
    ] = False,
    config_path: Annotated[
        Path | None,
        typer.Option("--config-path", "-c", help="Custom configuration path."),
    ] = None,
) -> None:
    """Scan git commit history to backfill historical contract mutations into LanceDB."""
    cfg = load_config(config_path)
    sources = resolve_sync_sources(
        config=cfg,
        repo_filter=repo,
        all_flag=(repo is None),
    )

    if not sources:
        console.print(f"[bold yellow]No repositories matched '{repo}'.[/bold yellow]")
        return

    engine = ContractEvolutionEngine.from_config(cfg)
    total_events = 0
    scanned_repos = 0

    for src in sources:
        if not src.enabled:
            continue
        scanned_repos += 1
        name = src.get_repo_name()
        if not json_output:
            console.print(f"[cyan]Scanning git history for '{name}'...[/cyan]")
        events = engine.scan_git_history(
            repo_path=src.path,
            repo_name=name,
            max_commits=max_commits,
            since_commit=since_commit,
        )
        total_events += len(events)
        if not json_output and events:
            console.print(f"  [green]✓ Recorded {len(events)} contract mutations[/green]")

    if json_output:
        console.print_json(
            data={
                "status": "ok",
                "scanned_repositories": scanned_repos,
                "total_events_recorded": total_events,
            }
        )
    else:
        console.print(
            f"\n[bold green]✓ Scanned {scanned_repos} repositories; "
            f"recorded {total_events} contract mutations.[/bold green]"
        )
