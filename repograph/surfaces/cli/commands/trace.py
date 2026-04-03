"""Trace commands: trace install/collect/report/clear."""
from __future__ import annotations

import json as _json
import os

import typer

from repograph.surfaces.cli.app import trace_app, console, _print_not_indexed_error


# ---------------------------------------------------------------------------
# repograph trace install
# ---------------------------------------------------------------------------

@trace_app.command("install")
def trace_install(
    path: str | None = typer.Argument(None, help="Repository root (default: cwd)."),
    mode: str = typer.Option(
        "pytest",
        "--mode", "-m",
        help="Instrumentation mode: 'pytest' (conftest.py) or 'sitecustomize'.",
    ),
    max_records: int = typer.Option(0, "--max-records", help="Max records per trace session (0 = unlimited)."),
    max_mb: int = typer.Option(0, "--max-mb", help="Max bytes per trace file in MB (0 = unlimited)."),
    rotate_files: int = typer.Option(0, "--rotate-files", help="Rotate at most N extra files when max-mb is reached."),
    sample_rate: float = typer.Option(1.0, "--sample-rate", help="Sampling rate for call records [0.0-1.0]."),
    include_pattern: str = typer.Option("", "--include", help="Regex include filter on 'file::qualified_name'."),
    exclude_pattern: str = typer.Option("", "--exclude", help="Regex exclude filter on 'file::qualified_name'."),
) -> None:
    """Write manual instrumentation config so the next Python/test run generates traces.

    Creates a conftest.py (or sitecustomize.py) inside .repograph/ that activates
    sys.settrace tracing and writes JSONL traces to .repograph/runtime/.
    """
    from repograph.settings import get_repo_root, repograph_dir as rg_dir_fn
    from repograph.exceptions import RepographNotFoundError
    from repograph.runtime.trace_format import trace_dir
    from repograph.plugins.lifecycle import get_hook_scheduler, ensure_all_plugins_registered

    try:
        root = get_repo_root(path)
    except RepographNotFoundError:
        # trace install does not require an initialized index — work from the given path
        root = os.path.abspath(path or os.getcwd())
    rg_dir = rg_dir_fn(root)
    td = trace_dir(rg_dir)

    ensure_all_plugins_registered()
    tracers = get_hook_scheduler().list_for_hook("on_tracer_install")
    if not tracers:
        console.print("[red]No tracer plugins registered.[/]")
        raise typer.Exit(1)

    from pathlib import Path
    from repograph.core.plugin_framework import TracerPlugin

    for tracer in tracers:
        if not isinstance(tracer, TracerPlugin):
            continue
        result = tracer.install(
            Path(root),
            td,
            mode=mode,
            max_records=max_records,
            max_file_bytes=max(0, int(max_mb)) * 1024 * 1024,
            rotate_files=rotate_files,
            sample_rate=sample_rate,
            include_pattern=include_pattern,
            exclude_pattern=exclude_pattern,
        )
        status = result.get("status", "?")
        config_path = result.get("config_path", "")
        if status == "already_installed":
            console.print(f"[yellow]Already installed:[/] {config_path}")
        else:
            console.print(f"[green]✓ Installed ({tracer.plugin_id()}):[/] {config_path}")
            console.print(f"  Traces will be written to: {result.get('trace_dir')}")
            console.print(
                "\nManual next steps:\n"
                "  1. Run your tests normally (e.g. [bold]pytest[/]) so JSONL appears under "
                "[bold].repograph/runtime/[/]\n"
                "  2. Then run [bold]repograph sync[/] to merge traces into [bold]graph.db[/] "
                "(required — [bold]repograph report[/] alone does not apply traces)\n"
                "  3. Or run [bold]repograph trace report[/] to inspect overlay findings first\n\n"
                "[dim]Routine users should prefer [bold]repograph sync --full[/], which now performs "
                "automatic runtime overlay without writing tracer files.[/]"
            )
            if mode == "sitecustomize":
                console.print(
                    "[dim]Sitecustomize mode is the bootstrap used for live Python attach. "
                    "After you restart a repo-scoped Python server with [bold].repograph[/] on "
                    "[bold]PYTHONPATH[/], [bold]repograph sync --full[/] can detect the active "
                    "RepoGraph session and capture a current attach delta automatically.[/]"
                )


# ---------------------------------------------------------------------------
# repograph trace collect
# ---------------------------------------------------------------------------

@trace_app.command("collect")
def trace_collect(
    path: str | None = typer.Argument(None),
    as_json: bool = typer.Option(False, "--json", help="Output trace inventory as JSON."),
) -> None:
    """List trace files collected in .repograph/runtime/."""
    from repograph.settings import get_repo_root, repograph_dir as rg_dir_fn
    from repograph.exceptions import RepographNotFoundError
    from repograph.runtime.trace_format import collect_live_trace_files, collect_trace_files

    try:
        root = get_repo_root(path)
    except RepographNotFoundError:
        _print_not_indexed_error()
        raise typer.Exit(1)
    rg_dir = rg_dir_fn(root)

    files = collect_trace_files(rg_dir)
    live_files = collect_live_trace_files(rg_dir)
    if not files and not live_files:
        console.print(
            "[yellow]No trace files in .repograph/runtime/.[/]\n"
            "  • Routine users should run [bold]repograph sync --full[/] first; it performs automatic runtime capture when supported.\n"
            "  • If you intentionally want manual trace files, run [bold]repograph trace install[/].\n"
            "  • After install, traces are created when Python runs with tracing active — "
            "typically [bold]pytest[/] at the repo root (conftest), or use "
            "[bold]repograph trace install --mode sitecustomize[/] to trace all "
            "`python` processes from this tree."
        )
        return

    total_lines = 0
    total_size_bytes = 0
    rows: list[dict[str, int | str]] = []
    for f in files:
        try:
            lines = sum(1 for _ in open(f, encoding="utf-8", errors="replace"))
        except OSError:
            lines = 0
        size_bytes = 0
        try:
            size_bytes = f.stat().st_size
        except OSError:
            size_bytes = 0
        total_lines += lines
        total_size_bytes += size_bytes
        rows.append({"name": f.name, "records": int(lines), "size_bytes": int(size_bytes)})
    live_total_lines = 0
    live_total_size_bytes = 0
    live_rows: list[dict[str, int | str]] = []
    for f in live_files:
        try:
            lines = sum(1 for _ in open(f, encoding="utf-8", errors="replace"))
        except OSError:
            lines = 0
        size_bytes = 0
        try:
            size_bytes = f.stat().st_size
        except OSError:
            size_bytes = 0
        live_total_lines += lines
        live_total_size_bytes += size_bytes
        live_rows.append({"name": f.name, "records": int(lines), "size_bytes": int(size_bytes)})

    if as_json:
        typer.echo(
            _json.dumps(
                {
                    "trace_files": rows,
                    "trace_file_count": len(rows),
                    "total_records": total_lines,
                    "total_size_bytes": total_size_bytes,
                    "live_trace_files": live_rows,
                    "live_trace_file_count": len(live_rows),
                    "live_total_records": live_total_lines,
                    "live_total_size_bytes": live_total_size_bytes,
                },
                indent=2,
            )
        )
        return

    for r in rows:
        rec = r["records"] if isinstance(r.get("records"), int) else 0
        console.print(f"  [cyan]{r['name']}[/]  {rec:,} records")

    if files:
        console.print(f"\n[green]{len(files)} trace file(s), {total_lines:,} total records.[/]")
    if live_rows:
        console.print("\n[cyan]Active live-session traces (not merged directly until attach capture):[/]")
        for r in live_rows:
            rec = r["records"] if isinstance(r.get("records"), int) else 0
            console.print(f"  [cyan]{r['name']}[/]  {rec:,} records")
        console.print(
            f"[cyan]{len(live_rows)} live trace file(s), {live_total_lines:,} total records.[/]"
        )
    console.print(
        "Run [bold]repograph sync[/] to merge traces into the graph (updates dead-code / "
        "[bold]runtime_*[/] fields). [bold]repograph report[/] only reads the existing index — "
        "it does not consume new JSONL by itself."
    )
    if live_rows:
        console.print(
            "[dim]Live-session traces come from long-running RepoGraph-traced Python processes. "
            "Run [bold]repograph sync --full[/] while the server is up to capture a current "
            "attach delta into overlay-ready trace files.[/]"
        )


# ---------------------------------------------------------------------------
# repograph trace report
# ---------------------------------------------------------------------------

@trace_app.command("report")
def trace_report(
    path: str | None = typer.Argument(None),
    top: int = typer.Option(20, "--top", "-n", help="Number of top-called functions to show."),
    json_out: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Show dynamic overlay findings from collected traces.

    Reads trace files from .repograph/runtime/ and reports:
    - Most frequently called functions
    - Functions marked dead statically but observed live at runtime
    - Dynamic call edges not visible to the static graph
    """
    from repograph.settings import get_repo_root, repograph_dir as rg_dir_fn
    from repograph.exceptions import RepographNotFoundError
    from repograph.runtime.trace_format import collect_live_trace_files, trace_dir, collect_trace_files
    from repograph.runtime.overlay import overlay_traces

    try:
        root = get_repo_root(path)
    except RepographNotFoundError:
        _print_not_indexed_error()
        raise typer.Exit(1)
    rg_dir = rg_dir_fn(root)
    td = trace_dir(rg_dir)

    overlay_files = collect_trace_files(rg_dir)
    live_files = collect_live_trace_files(rg_dir)
    if not overlay_files:
        if live_files:
            console.print(
                "[yellow]No overlay-ready trace files.[/] "
                "Active live-session traces exist under [bold].repograph/runtime/live/[/], "
                "but [bold]repograph trace report[/] only analyzes captured overlay inputs. "
                "Run [bold]repograph sync --full[/] while the live server is up to capture a "
                "current attach delta, or use managed runtime/traced tests."
            )
            return
        console.print(
            "[yellow]No trace files.[/] Start with [bold]repograph sync --full[/] for the normal runtime path. "
            "If you intentionally want a manual tracing session, run [bold]pytest[/] after "
            "[bold]repograph trace install[/], or use [bold]--mode sitecustomize[/]."
        )
        return

    # Open the graph store for overlay
    from repograph.settings import db_path, is_initialized
    if not is_initialized(root):
        console.print("[red]Not initialized.[/] Run [bold]repograph sync[/] first.")
        raise typer.Exit(1)

    from repograph.graph_store.store import GraphStore
    store = GraphStore(db_path(root))
    store.prepare_read_state()

    try:
        report = overlay_traces(td, store, repo_root=root)
    finally:
        store.close()

    if json_out:
        console.print(_json.dumps(report, indent=2))
        return

    console.print(f"\n[bold]Dynamic Overlay Report[/]")
    console.print(
        f"  Trace files:      {report['trace_file_count']}\n"
        f"  Observed fns:     {report['observed_fn_count']}\n"
        f"  New dynamic edges:{report['new_edge_count']}\n"
        f"  Trace calls:      {report.get('trace_call_records', 0)}\n"
        f"  Resolved calls:   {report.get('resolved_trace_calls', 0)}\n"
        f"  Unresolved calls: {report.get('unresolved_trace_calls', 0)}\n"
    )

    if report["top_calls"]:
        console.print("[bold]Top called functions:[/]")
        for fn, count in report["top_calls"][:top]:
            console.print(f"  {count:6,}×  {fn}")
        console.print()

    static_dead_live = [
        f for f in report["findings"]
        if f.get("kind") == "observed_live_but_static_dead"
    ]
    if static_dead_live:
        console.print(f"[bold yellow]⚠  {len(static_dead_live)} function(s) static-dead but observed live:[/]")
        for f in static_dead_live[:10]:
            console.print(f"  {f.get('function_id', '?')}")
        console.print()

    new_edges = [f for f in report["findings"] if f.get("kind") == "dynamic_call_edge"]
    if new_edges:
        console.print(f"[bold blue]  {len(new_edges)} dynamic edge(s) not in static graph:[/]")
        for e in new_edges[:10]:
            console.print(f"  {e['caller']} → {e['callee']}  ({e['file']}:{e['line']})")
    unresolved = report.get("unresolved_examples") or []
    if unresolved:
        console.print(f"[bold yellow]Unresolved trace symbols ({len(unresolved)} shown):[/]")
        for u in unresolved[:10]:
            console.print(f"  {u}")


# ---------------------------------------------------------------------------
# repograph trace clear
# ---------------------------------------------------------------------------

@trace_app.command("clear")
def trace_clear(
    path: str | None = typer.Argument(None),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete all collected trace files from .repograph/runtime/."""
    import shutil
    from repograph.settings import get_repo_root, repograph_dir as rg_dir_fn
    from repograph.exceptions import RepographNotFoundError
    from repograph.runtime.trace_format import trace_dir

    try:
        root = get_repo_root(path)
    except RepographNotFoundError:
        _print_not_indexed_error()
        raise typer.Exit(1)
    td = trace_dir(rg_dir_fn(root))

    if not td.exists():
        console.print("[yellow]No traces to clear.[/]")
        return
    if not yes:
        typer.confirm(f"Delete all traces in {td}?", abort=True)
    shutil.rmtree(td)
    console.print(f"[green]Cleared {td}[/]")
