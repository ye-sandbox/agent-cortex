"""Common utilities, Rich console instance, and formatters for agent-cortex CLI."""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console

from cortex.models.drift import DriftSeverity

console = Console()


def _format_bytes(num: int | float) -> str:
    """Format bytes into human-readable string (B, KiB, MiB, GiB, TiB)."""
    n = float(num)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(n) < 1024.0:
            return f"{n:3.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TiB"


def _parse_cli_val(raw: str) -> Any:
    cleaned = raw.strip()
    if cleaned.lower() in ("true", "yes"):
        return True
    if cleaned.lower() in ("false", "no"):
        return False
    try:
        return int(cleaned)
    except ValueError:
        pass
    try:
        return float(cleaned)
    except ValueError:
        pass
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    return cleaned


def _nest_key_path(key_path: str, val: Any) -> dict[str, Any]:
    parts = [p.strip() for p in key_path.split(".") if p.strip()]
    if not parts:
        return {}
    res: dict[str, Any] = {}
    curr = res
    for part in parts[:-1]:
        curr[part] = {}
        curr = curr[part]
    curr[parts[-1]] = val
    return res


def _format_severity_badge(sev: DriftSeverity) -> str:
    match sev:
        case DriftSeverity.CRITICAL:
            return "[bold red]CRITICAL[/bold red]"
        case DriftSeverity.HIGH:
            return "[bold yellow]HIGH[/bold yellow]"
        case DriftSeverity.MEDIUM:
            return "[blue]MEDIUM[/blue]"
        case DriftSeverity.LOW:
            return "[dim]LOW[/dim]"
        case DriftSeverity.INFO:
            return "[dim green]INFO[/dim green]"
