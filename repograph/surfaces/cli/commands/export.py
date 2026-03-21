"""Export command."""
from __future__ import annotations

import json

import typer

from repograph.surfaces.cli.app import app, console, _get_root_and_store


# ---------------------------------------------------------------------------
# repograph export
# ---------------------------------------------------------------------------

@app.command()
def export(
    output: str = typer.Option("repograph_export.json", "--output", "-o"),
    path: str | None = typer.Argument(None),
):
    """Export the full graph as JSON."""
    root, store = _get_root_and_store(path)

    data = {
        "stats": store.get_stats(),
        "functions": store.get_all_functions(),
        "call_edges": store.get_all_call_edges(),
        "pathways": store.get_all_pathways(),
        "entry_points": store.get_entry_points(),
        "dead_code": store.get_dead_functions(),
    }
    with open(output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    console.print(f"[green]Exported to {output}[/]")
