"""Shared Rich output helpers for the CLI surface."""
from __future__ import annotations

from rich.table import Table
from repograph.surfaces.cli.app import console


def _print_stats(stats: dict) -> None:
    table = Table(title="Index Stats", show_header=True)
    table.add_column("Entity", style="cyan")
    table.add_column("Count", justify="right", style="green")
    for key, val in stats.items():
        table.add_row(key.replace("_", " ").title(), str(val))
    console.print(table)
