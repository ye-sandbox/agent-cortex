"""Dynamic runtime configuration and multi-tenant management CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from cortex.cli.common import _nest_key_path, _parse_cli_val, console
from cortex.config.dynamic import DynamicConfigManager, deep_merge
from cortex.config.loader import load_config
from cortex.config.migration import migrate_static_to_db

config_app = typer.Typer(
    name="config",
    help="Manage dynamic runtime configuration tables and multi-tenant profiles.",
    no_args_is_help=True,
)


@config_app.command(name="show")
def config_show(
    tenant: Annotated[
        str,
        typer.Option("--tenant", "-t", help="Tenant identifier (defaults to 'default')."),
    ] = "default",
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to cortex configuration YAML file.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            "-j",
            help="Emit strictly valid JSON output for machine parsing.",
        ),
    ] = False,
) -> None:
    """Display resolved configuration for a tenant (combining base and dynamic overrides)."""
    base_cfg = load_config(config_path)
    dyn_mgr = DynamicConfigManager(data_dir=base_cfg.storage.data_dir)
    resolved = dyn_mgr.get_tenant_config(tenant, fallback=base_cfg)
    raw_override = dyn_mgr.get_raw_config(tenant)

    payload = {
        "tenant_id": tenant,
        "has_dynamic_override": raw_override is not None,
        "dynamic_override": raw_override if raw_override is not None else {},
        "effective_config": resolved.model_dump(mode="json"),
    }

    if json_output:
        console.print_json(data=payload)
        return

    table = Table(
        title=f"Configuration for Tenant: {tenant}",
        title_style="bold cyan",
        header_style="bold magenta",
    )
    table.add_column("Parameter", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Hardware Profile", resolved.profile.value)
    table.add_row("Storage Dir", str(resolved.storage.data_dir))
    table.add_row("Retrieval RRF (k)", str(resolved.retrieval.k))
    table.add_row("RRF Dense Weight", f"{resolved.retrieval.weight_dense:.2f}")
    table.add_row("RRF Sparse Weight", f"{resolved.retrieval.weight_sparse:.2f}")
    table.add_row("Archived Penalty", f"{resolved.retrieval.archived_penalty:.2f}")
    table.add_row("Default Limit", str(resolved.retrieval.default_limit))
    table.add_row("Dynamic Override in DB", "Yes" if raw_override else "No (using fallback)")

    console.print(table)


@config_app.command(name="set")
def config_set(
    key: Annotated[
        str,
        typer.Argument(help="Configuration key path (e.g. 'profile', 'retrieval.default_limit')."),
    ],
    value: Annotated[
        str,
        typer.Argument(help="Configuration value (auto-coerced to int/float/bool/json/str)."),
    ],
    tenant: Annotated[
        str,
        typer.Option("--tenant", "-t", help="Tenant identifier (defaults to 'default')."),
    ] = "default",
    description: Annotated[
        str,
        typer.Option("--description", "-d", help="Optional description/reason for update."),
    ] = "",
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to cortex configuration YAML file.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            "-j",
            help="Emit strictly valid JSON output for machine parsing.",
        ),
    ] = False,
) -> None:
    """Dynamically set a configuration value for a tenant in the LanceDB runtime table."""
    base_cfg = load_config(config_path)
    dyn_mgr = DynamicConfigManager(data_dir=base_cfg.storage.data_dir)

    parsed_val = _parse_cli_val(value)
    nested_update = _nest_key_path(key, parsed_val)

    existing_raw = dyn_mgr.get_raw_config(tenant) or {}
    updated_raw = deep_merge(existing_raw, nested_update)

    try:
        saved = dyn_mgr.set_tenant_config(tenant, updated_raw, description=description)
    except Exception as exc:
        if json_output:
            console.print_json(data={"status": "error", "detail": str(exc)})
        else:
            console.print(f"[bold red]Failed to update configuration:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    if json_output:
        console.print_json(data={"status": "ok", "tenant_id": tenant, "config": saved})
        return

    console.print(
        f"[bold green]Updated[/bold green] [cyan]{key}[/cyan] = [yellow]{parsed_val}[/yellow] "
        f"for tenant '[magenta]{tenant}[/magenta]' in DB."
    )


@config_app.command(name="list-tenants")
def config_list_tenants(
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to cortex configuration YAML file.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            "-j",
            help="Emit strictly valid JSON output for machine parsing.",
        ),
    ] = False,
) -> None:
    """List all tenants with registered dynamic configurations in the LanceDB table."""
    base_cfg = load_config(config_path)
    dyn_mgr = DynamicConfigManager(data_dir=base_cfg.storage.data_dir)
    tenants = dyn_mgr.list_tenants()

    if json_output:
        console.print_json(data={"total_tenants": len(tenants), "tenants": tenants})
        return

    if not tenants:
        console.print("[dim]No dynamic tenant configurations registered in DB.[/dim]")
        return

    table = Table(title="Registered Tenant Configurations", header_style="bold magenta")
    table.add_column("Tenant ID", style="cyan")
    table.add_column("Last Updated (UTC)", style="dim")
    table.add_column("Description", style="white")

    for t in tenants:
        table.add_row(
            str(t.get("tenant_id", "")),
            str(t.get("updated_at", "")),
            str(t.get("description", "")),
        )
    console.print(table)


@config_app.command(name="delete")
def config_delete(
    tenant: Annotated[
        str,
        typer.Option("--tenant", "-t", help="Tenant identifier to delete."),
    ],
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to cortex configuration YAML file.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            "-j",
            help="Emit strictly valid JSON output for machine parsing.",
        ),
    ] = False,
) -> None:
    """Delete dynamic configuration overrides for a tenant."""
    base_cfg = load_config(config_path)
    dyn_mgr = DynamicConfigManager(data_dir=base_cfg.storage.data_dir)
    deleted = dyn_mgr.delete_tenant_config(tenant)

    if json_output:
        console.print_json(
            data={
                "status": "ok" if deleted else "not_found",
                "tenant_id": tenant,
                "deleted": deleted,
            }
        )
        return

    if deleted:
        console.print(
            f"[bold green]Deleted dynamic configuration for tenant '{tenant}'.[/bold green]"
        )
    else:
        console.print(f"[yellow]No dynamic configuration found for tenant '{tenant}'.[/yellow]")


@config_app.command(name="migrate")
def config_migrate(
    tenant: Annotated[
        str,
        typer.Option("--tenant", "-t", help="Target tenant identifier (defaults to 'default')."),
    ] = "default",
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite", "--force", help="Overwrite existing tenant configuration in DB."
        ),
    ] = False,
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to cortex configuration YAML file.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            "-j",
            help="Emit strictly valid JSON output for machine parsing.",
        ),
    ] = False,
) -> None:
    """Migrate static YAML configuration into the DB-backed runtime configuration table."""
    base_cfg = load_config(config_path)
    dyn_mgr = DynamicConfigManager(data_dir=base_cfg.storage.data_dir)
    migrated = migrate_static_to_db(
        config=base_cfg, manager=dyn_mgr, tenant_id=tenant, overwrite=overwrite
    )

    if json_output:
        console.print_json(data={"status": "ok", "tenant_id": tenant, "migrated": migrated})
        return

    if migrated:
        console.print(
            f"[bold green]Successfully migrated static configuration to DB table "
            f"for tenant '{tenant}'.[/bold green]"
        )
    else:
        console.print(
            f"[yellow]Tenant '{tenant}' already exists in DB. Use --overwrite to replace.[/yellow]"
        )
