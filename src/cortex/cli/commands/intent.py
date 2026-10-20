"""Cross-repository portfolio change intent simulation and contract patch CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

import cortex.cli
from cortex.cli.common import console
from cortex.client import ClientMode
from cortex.config.loader import load_config
from cortex.models.impact import BlastRadiusSeverity
from cortex.models.intent import (
    ChangeIntentAction,
    ChangeIntentSimulationReport,
    ContractChangeIntent,
    PortfolioChangePlan,
)


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


intent_app = typer.Typer(
    name="intent",
    help="Simulate cross-repository change intents and synthesize automated contract patches.",
    no_args_is_help=True,
)


def _resolve_plan(
    repo: str | None,
    symbol: str | None,
    action: str,
    new_symbol: str | None,
    file_path: str | None,
    plan_path: Path | None,
) -> PortfolioChangePlan:
    """Resolve single intent CLI options or plan file into PortfolioChangePlan."""
    if plan_path:
        if not plan_path.is_file():
            console.print(f"[bold red]Error:[/bold red] Plan file '{plan_path}' does not exist.")
            raise typer.Exit(code=1)
        try:
            raw_data = json.loads(plan_path.read_text(encoding="utf-8"))
            if "intents" in raw_data:
                return PortfolioChangePlan.model_validate(raw_data)
            intent = ContractChangeIntent.model_validate(raw_data)
            return PortfolioChangePlan(
                plan_id=intent.intent_id or "plan_from_file",
                title=f"Plan from {plan_path.name}",
                intents=[intent],
            )
        except Exception as exc:
            console.print(f"[bold red]Error parsing plan file:[/bold red] {exc}")
            raise typer.Exit(code=1) from exc

    if not repo or not symbol:
        console.print(
            "[bold red]Error:[/bold red] Either specify both REPO and --symbol, "
            "or provide --plan <file.json>."
        )
        raise typer.Exit(code=1)

    act_enum = ChangeIntentAction.RENAME_SYMBOL
    act_str = action.strip().upper()
    for member in ChangeIntentAction:
        if member.value == act_str or member.name == act_str:
            act_enum = member
            break

    intent = ContractChangeIntent(
        repo=repo.strip(),
        target_symbol=symbol.strip(),
        action=act_enum,
        new_symbol=new_symbol.strip() if new_symbol else None,
        file_path=file_path.strip() if file_path else None,
    )
    return PortfolioChangePlan(
        plan_id=intent.intent_id,
        title=f"Intent: {intent.action.value} {intent.target_symbol}",
        intents=[intent],
    )


@intent_app.command(name="simulate")
def intent_simulate(
    repo: Annotated[
        str | None,
        typer.Argument(
            help="Target repository where contract originates (optional if --plan given)."
        ),
    ] = None,
    symbol: Annotated[
        str | None,
        typer.Option("--symbol", "-s", help="Target contract symbol or endpoint to modify."),
    ] = None,
    action: Annotated[
        str,
        typer.Option(
            "--action",
            "-a",
            help="Intent action: RENAME_SYMBOL, MODIFY_SIGNATURE, CHANGE_ENDPOINT, etc.",
        ),
    ] = "RENAME_SYMBOL",
    new_symbol: Annotated[
        str | None,
        typer.Option("--new-symbol", "-n", help="Replacement symbol, signature, or endpoint path."),
    ] = None,
    file_path: Annotated[
        str | None,
        typer.Option("--file", "-f", help="Target file path in repository."),
    ] = None,
    plan_path: Annotated[
        Path | None,
        typer.Option("--plan", "-p", help="Path to JSON file containing PortfolioChangePlan."),
    ] = None,
    max_depth: Annotated[
        int,
        typer.Option("--max-depth", "-d", help="Max transitive caller traversal depth."),
    ] = 5,
    generate_patches: Annotated[
        bool,
        typer.Option(
            "--generate-patches/--no-patches",
            help="Whether to synthesize automated unified diff patches for downstream consumers.",
        ),
    ] = True,
    fail_on_risk: Annotated[
        bool,
        typer.Option(
            "--fail-on-risk",
            help="Exit with code 1 if simulation evaluates to CRITICAL or HIGH risk.",
        ),
    ] = False,
    fail_on_violations: Annotated[
        bool,
        typer.Option(
            "--fail-on-violations",
            help="Exit with code 1 if simulation detects architectural violations.",
        ),
    ] = False,
    remote: Annotated[
        bool,
        typer.Option("--remote", help="Query remote Cortex HTTP hub daemon."),
    ] = False,
    config_path: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to config.yaml."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output machine-readable JSON simulation report."),
    ] = False,
) -> None:
    """Simulate portfolio-wide blast radius and violations for declared change intents."""
    plan = _resolve_plan(repo, symbol, action, new_symbol, file_path, plan_path)

    cfg = load_config(config_path)
    mode: ClientMode = "remote" if remote else "in_process"
    client = cortex.cli.CortexClient(config=cfg, mode=mode)

    try:
        report = client.simulate_change_intent(
            plan=plan,
            max_depth=max_depth,
            generate_patches=generate_patches,
        )
    except Exception as exc:
        console.print(f"[bold red]Simulation error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    if json_output:
        print(report.model_dump_json(indent=2))
        _check_exit_flags(report, fail_on_risk, fail_on_violations)
        return

    # Visual Rich Presentation
    badge = _format_risk_badge(report.overall_risk_level)
    lines = [
        f"Plan ID: [bold cyan]{report.plan_id}[/bold cyan]",
        f"Overall Risk: {badge}  Score: [bold]{report.overall_risk_score:.1f}[/bold]/100.0",
        f"Intents: [bold]{report.total_intents}[/bold] | "
        f"Affected Repos: [bold]{len(report.affected_repos)}[/bold] | "
        f"Call Sites: [bold]{report.total_call_sites}[/bold]",
    ]
    if report.affected_repos:
        lines.append(f"Affected Repositories: [dim]{', '.join(report.affected_repos)}[/dim]")

    console.print(
        Panel(
            "\n".join(lines),
            title="[bold blue]Portfolio Change Intent Simulation[/bold blue]",
            border_style="cyan",
        )
    )

    # 1. Violations Table
    if report.violations:
        table_v = Table(title="Architectural Violations & Drift Risks", show_lines=True)
        table_v.add_column("Severity", justify="center", style="bold")
        table_v.add_column("Category", style="cyan")
        table_v.add_column("Description")
        table_v.add_column("Consumer Site", style="dim")

        for v in report.violations:
            loc = (
                f"{v.call_site.repo}:{v.call_site.file_path}:{v.call_site.line_number}"
                if v.call_site
                else "Portfolio Scope"
            )
            table_v.add_row(_format_risk_badge(v.severity), v.category, v.message, loc)
        console.print(table_v)

    # 2. Downstream Call Sites Table
    if report.call_sites:
        table_s = Table(title="Downstream Consumer Call Sites", show_lines=False)
        table_s.add_column("Repo", style="bold green")
        table_s.add_column("File", style="cyan")
        table_s.add_column("Line", justify="right")
        table_s.add_column("Matched Symbol")
        table_s.add_column("Statement", style="dim")

        for s in report.call_sites[:25]:
            stmt = s.raw_statement.strip()
            table_s.add_row(s.repo, s.file_path, str(s.line_number), s.matched_symbol, stmt[:60])
        if len(report.call_sites) > 25:
            console.print(f"[dim]... and {len(report.call_sites) - 25} more call sites[/dim]")
        console.print(table_s)

    # 3. Migration Patches Summary
    if report.migration_patches:
        table_p = Table(title="Automated Migration Patches Available", show_lines=True)
        table_p.add_column("Repo", style="bold green")
        table_p.add_column("Files", justify="right")
        table_p.add_column("Hunks", justify="right")
        table_p.add_column("Resolved Breaking", justify="right")

        for p in report.migration_patches:
            table_p.add_row(
                p.repo,
                str(p.total_files),
                str(len(p.hunks)),
                str(p.breaking_changes_resolved),
            )
        console.print(table_p)

    # 4. Recommended Staging Order
    if report.execution_order:
        console.print(
            "\n[bold cyan]Recommended Staging Order (Topological Leaves First):[/bold cyan]"
        )
        for idx, r in enumerate(report.execution_order, 1):
            console.print(f"  {idx}. [green]{r}[/green]")

    _check_exit_flags(report, fail_on_risk, fail_on_violations)


def _check_exit_flags(
    report: ChangeIntentSimulationReport, fail_on_risk: bool, fail_on_violations: bool
) -> None:
    """Exit with error code if gates triggered."""
    if fail_on_risk and report.overall_risk_level.is_breaking:
        console.print(
            "\n[bold red]Simulation risk gate failed (CRITICAL or HIGH risk detected).[/bold red]"
        )
        raise typer.Exit(code=1)
    if fail_on_violations and report.violations:
        console.print(
            "\n[bold red]Simulation violation gate failed (Violations detected).[/bold red]"
        )
        raise typer.Exit(code=1)


@intent_app.command(name="patch")
def intent_patch(
    repo: Annotated[
        str | None,
        typer.Argument(
            help="Target repository where contract originates (optional if --plan given)."
        ),
    ] = None,
    symbol: Annotated[
        str | None,
        typer.Option("--symbol", "-s", help="Target contract symbol or endpoint to modify."),
    ] = None,
    action: Annotated[
        str,
        typer.Option(
            "--action",
            "-a",
            help="Intent action: RENAME_SYMBOL, MODIFY_SIGNATURE, CHANGE_ENDPOINT, etc.",
        ),
    ] = "RENAME_SYMBOL",
    new_symbol: Annotated[
        str | None,
        typer.Option("--new-symbol", "-n", help="Replacement symbol, signature, or endpoint path."),
    ] = None,
    file_path: Annotated[
        str | None,
        typer.Option("--file", "-f", help="Target file path in repository."),
    ] = None,
    plan_path: Annotated[
        Path | None,
        typer.Option("--plan", "-p", help="Path to JSON file containing PortfolioChangePlan."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", "-o", help="Optional directory to save <repo>.patch files."),
    ] = None,
    remote: Annotated[
        bool,
        typer.Option("--remote", help="Query remote Cortex HTTP hub daemon."),
    ] = False,
    config_path: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to config.yaml."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output raw JSON array of RepoMigrationPatch."),
    ] = False,
) -> None:
    """Synthesize automated unified diff migration patches across downstream consumers."""
    plan = _resolve_plan(repo, symbol, action, new_symbol, file_path, plan_path)

    cfg = load_config(config_path)
    mode: ClientMode = "remote" if remote else "in_process"
    client = cortex.cli.CortexClient(config=cfg, mode=mode)

    try:
        patches = client.generate_contract_patches(plan=plan)
    except Exception as exc:
        console.print(f"[bold red]Patch generation error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    if json_output:
        data = [p.model_dump(mode="json") for p in patches]
        print(json.dumps(data, indent=2))
        return

    if not patches:
        console.print(
            "[dim]No migration patches synthesized "
            "(no downstream callers or changes required).[/dim]"
        )
        return

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        for p in patches:
            p_file = output_dir / f"{p.repo}.patch"
            p_file.write_text(p.unified_diff, encoding="utf-8")
            console.print(
                f"Wrote patch for [bold green]{p.repo}[/bold green] -> [cyan]{p_file}[/cyan]"
            )
        return

    # Print patches with diff syntax highlighting
    for p in patches:
        title_str = (
            f"[bold green]Patch: {p.repo}[/bold green] "
            f"({p.total_files} file(s), {p.breaking_changes_resolved} breaking resolved)"
        )
        console.print(
            Panel(
                Syntax(
                    p.unified_diff or "# Empty diff", "diff", theme="monokai", line_numbers=False
                ),
                title=title_str,
                border_style="green",
            )
        )
