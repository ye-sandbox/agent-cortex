"""Search command implementation for agent-cortex CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.markup import escape
from rich.panel import Panel

import cortex.cli
from cortex.cli.common import console
from cortex.client import ClientMode, CortexRemoteError
from cortex.config.loader import load_config
from cortex.models.chunk import ChunkCategory, ChunkScope


def search_cmd(
    query: Annotated[
        str,
        typer.Argument(help="Semantic query to search across portfolio knowledge."),
    ],
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile",
            "-p",
            help="Hardware profile tier override (high, balanced, low, code).",
        ),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            "-l",
            help="Maximum number of search results to return.",
        ),
    ] = None,
    scope: Annotated[
        str | None,
        typer.Option(
            "--scope",
            "-s",
            help="Scope filter (internal, public, confidential, or comma-separated).",
        ),
    ] = None,
    include_archived: Annotated[
        bool,
        typer.Option(
            "--include-archived",
            help="Include archived chunks without score penalty.",
        ),
    ] = False,
    category: Annotated[
        str | None,
        typer.Option(
            "--category",
            help="Filter by category (doc, contract, infra, invariant, solution).",
        ),
    ] = None,
    repo: Annotated[
        str | None,
        typer.Option(
            "--repo",
            "-r",
            help="Filter results by repository name.",
        ),
    ] = None,
    rerank: Annotated[
        bool,
        typer.Option(
            "--rerank/--no-rerank",
            help="Enable or disable Stage 2 cross-encoder reranking.",
        ),
    ] = True,
    remote: Annotated[
        bool | None,
        typer.Option(
            "--remote/--local",
            help="Force querying remote hub or local in-process storage.",
        ),
    ] = None,
    hub_url: Annotated[
        str | None,
        typer.Option(
            "--hub-url",
            help="Remote agent-cortex hub endpoint override (e.g. 'http://homelab:8000').",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Stream machine-readable NDJSON output for AI agent subshell invocation.",
        ),
    ] = False,
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config-path",
            "-c",
            help="Custom configuration path.",
        ),
    ] = None,
) -> None:
    """Search portfolio documentation, OpenAPI contracts, and infrastructure definitions."""
    cleaned_query = query.strip()
    if not cleaned_query:
        if json_output:
            return
        console.print("[yellow]Empty query provided.[/yellow]")
        return

    cfg = load_config(config_path)

    # Parse scopes
    scopes: list[ChunkScope] | None = None
    if scope:
        scopes = []
        for s in scope.split(","):
            s_clean = s.strip().lower()
            if s_clean:
                try:
                    scopes.append(ChunkScope(s_clean))
                except ValueError:
                    console.print(f"[bold red]Error:[/bold red] Invalid scope '{s_clean}'.")
                    raise typer.Exit(code=1) from None

    # Parse category
    cat: ChunkCategory | None = None
    if category:
        try:
            cat = ChunkCategory(category.strip().lower())
        except ValueError:
            console.print(f"[bold red]Error:[/bold red] Invalid category '{category}'.")
            raise typer.Exit(code=1) from None

    mode: ClientMode = "auto"
    if remote is True:
        mode = "remote"
    elif remote is False:
        mode = "in_process"

    local_pipeline = (
        cortex.cli.HybridRetrievalPipeline.from_config(cfg, profile_override=profile)
        if profile
        else None
    )

    client = cortex.cli.CortexClient(
        mode=mode,
        hub_url=hub_url,
        config=cfg,
        pipeline=local_pipeline,
    )

    try:
        if json_output:
            for res in client.search_stream(
                query=cleaned_query,
                limit=limit,
                scopes=scopes,
                include_archived=include_archived,
                category=cat,
                repo=repo,
                rerank=rerank,
            ):
                typer.echo(res.model_dump_json())
            return

        results = client.search(
            query=cleaned_query,
            limit=limit,
            scopes=scopes,
            include_archived=include_archived,
            category=cat,
            repo=repo,
            rerank=rerank,
        )
    except CortexRemoteError as exc:
        target_hub = (
            exc.hub_url
            or client.hub_url
            or hub_url
            or (cfg.remote.hub_url if cfg.remote else None)
            or "unknown"
        )
        panel_content = (
            f"[bold red]Remote Hub Connection Failed[/bold red]\n\n"
            f"Target: [cyan]{escape(str(target_hub))}[/cyan]\n"
            f"Reason: [dim]{escape(str(exc))}[/dim]\n\n"
            f"[yellow]Diagnostic:[/yellow]\n"
            f"• Verify that the daemon is running (`cortex serve`) or network connectivity.\n"
            f"• Run with `--local` to query the local embedded LanceDB database directly."
        )
        console.print(Panel(panel_content, title="Connection Error", border_style="red"))
        raise typer.Exit(code=1) from None
    except Exception as exc:
        console.print(f"[bold red]Search failed:[/bold red] {exc}")
        raise typer.Exit(code=1) from None

    if not results:
        console.print("[yellow]No matching chunks found.[/yellow]")
        return

    console.print(
        f"[bold cyan]agent-cortex[/bold cyan] found [green]{len(results)}[/green] "
        "matching chunk(s):\n"
    )

    for rank, r in enumerate(results, start=1):
        repo_badge = f"[bold cyan]{escape(f'[{r.repo}]')}[/bold cyan]"
        breadcrumb_str = f" > [yellow]{escape(r.breadcrumb)}[/yellow]" if r.breadcrumb else ""
        console.print(
            f"[bold green]#{rank}[/bold green] {repo_badge} "
            f"[bold]{escape(r.file_path)}[/bold]{breadcrumb_str} "
            f"[dim](score: {r.score:.4f}, scope: {r.scope.value}, {r.category.value})[/dim]"
        )
        if r.snippet:
            indented = "    " + r.snippet.replace("\n", "\n    ")
            console.print(f"[dim]{indented}[/dim]")
        if r.tags:
            tag_str = " ".join(f"[blue]#{t}[/blue]" for t in r.tags[:6])
            console.print(f"    {tag_str}")
        console.print()
