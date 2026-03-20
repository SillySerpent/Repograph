"""Full report CLI command."""
from __future__ import annotations

import json as _json
import os

import typer

from repograph.surfaces.cli.app import app, console, _get_root_and_store
from repograph.surfaces.cli.report_renderers import render_full_report


# ---------------------------------------------------------------------------
# repograph report
# ---------------------------------------------------------------------------

@app.command()
def report(
    path: str | None = typer.Argument(
        None,
        help='Repository root (default: current directory). Do not use a bare "full" as the path — use --full.',
    ),
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON (machine-readable, all fields)."),
    full: bool = typer.Option(
        False,
        "--full",
        help=(
            "With --json, write the full uncapped report to .repograph/report.json. "
            "Terminal output stays capped to a readable size."
        ),
    ),
    max_pathways: int = typer.Option(10, "--pathways", "-p", help="Max pathways to include (default 10)."),
    max_dead: int = typer.Option(20, "--dead", "-d", help="Max dead-code symbols per tier (default 20)."),
) -> None:
    """Full intelligence report — every insight the tool has in one command.

    Aggregates: purpose, stats, module map, entry points, top pathway
    summaries, dead code, duplicates (with canonical guidance),
    invariants, config registry, test coverage, doc warnings, and communities.

    Ideal as a single context-injection for an AI entering an unfamiliar repo,
    or as a human-readable health check before a release.
    """
    from repograph.surfaces.api import RepoGraph
    from repograph.settings import repograph_dir

    if path is not None and path.strip().lower() == "full":
        path = None

    root, store = _get_root_and_store(path)
    store.close()

    # The human terminal report is always capped to a readable size. The full,
    # uncapped dump exists for machine-readable export via `--json --full`.
    show_all = False
    pathway_step_map: dict[str, list[dict]] = {}
    with RepoGraph(root, repograph_dir=repograph_dir(root)) as rg:
        data = rg.full_report(
            max_pathways=None if (as_json and full) else max_pathways,
            max_dead=None if (as_json and full) else max_dead,
            entry_point_limit=None if (as_json and full) else 20,
            max_config_keys=None if (as_json and full) else 30,
            max_communities=None if (as_json and full) else 20,
        )
        if not as_json:
            for pw in data.get("pathways", []):
                name = str(pw.get("name") or "").strip()
                if not name:
                    continue
                try:
                    pathway_step_map[name] = rg.pathway_steps(name)
                except Exception:
                    pathway_step_map[name] = []

    if as_json:
        if full:
            rg_path = os.path.join(repograph_dir(root), "report.json")
            os.makedirs(os.path.dirname(rg_path), exist_ok=True)
            with open(rg_path, "w", encoding="utf-8") as f:
                _json.dump(data, f, indent=2, default=str, ensure_ascii=False)
                f.write("\n")
            console.print(f"[green]Wrote[/] {rg_path}")
            return
        import sys
        sys.stdout.write(_json.dumps(data, indent=2, default=str, ensure_ascii=False))
        sys.stdout.write("\n")
        return

    render_full_report(
        console,
        data,
        pathway_step_map=pathway_step_map,
        full_requested=full,
        show_all=show_all,
    )
