"""Analysis commands: events, interfaces, deps, invariants, test-map."""
from __future__ import annotations

import json as _json

import typer
from rich.table import Table

from repograph.surfaces.cli.app import app, console, _get_root_and_store


# ---------------------------------------------------------------------------
# repograph events
# ---------------------------------------------------------------------------

@app.command("events")
def events_cmd(
    path: str | None = typer.Argument(None),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Event topology: publish/subscribe style call sites (Phase 19)."""
    from repograph.surfaces.api import RepoGraph
    from repograph.settings import repograph_dir

    root, store = _get_root_and_store(path)
    store.close()
    with RepoGraph(root, repograph_dir=repograph_dir(root)) as rg:
        if not rg._is_initialized():
            console.print("[red]Not initialized. Run [bold]repograph sync[/] first.[/]")
            raise typer.Exit(1)
        rows = rg.event_topology()
    if as_json:
        console.print(_json.dumps(rows, indent=2))
        return
    for r in rows[:80]:
        console.print(
            f"  [cyan]{r.get('event_type', '?')}[/]  "
            f"[dim]{r.get('role', '')}[/]  {r.get('file_path', '')}:{r.get('line', '')}"
        )


# ---------------------------------------------------------------------------
# repograph interfaces
# ---------------------------------------------------------------------------

@app.command("interfaces")
def interfaces_cmd(
    path: str | None = typer.Argument(None),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Interface map: classes with EXTENDS/IMPLEMENTS edges."""
    from repograph.surfaces.api import RepoGraph
    from repograph.settings import repograph_dir

    root, store = _get_root_and_store(path)
    store.close()
    with RepoGraph(root, repograph_dir=repograph_dir(root)) as rg:
        if not rg._is_initialized():
            console.print("[red]Not initialized. Run [bold]repograph sync[/] first.[/]")
            raise typer.Exit(1)
        data = rg.interface_map()
    if as_json:
        console.print(_json.dumps(data, indent=2))
        return
    for block in data[:40]:
        console.print(f"\n[bold]{block.get('interface', '?')}[/]  [dim]{block.get('interface_file', '')}[/]")
        for impl in block.get("implementations", [])[:12]:
            console.print(f"  • {impl.get('class', '')}  [dim]{impl.get('file_path', '')}[/]")


# ---------------------------------------------------------------------------
# repograph deps
# ---------------------------------------------------------------------------

@app.command("deps")
def deps_cmd(
    symbol: str = typer.Argument(..., help="Class name (unqualified)"),
    path: str | None = typer.Option(None, "--path", help="Repository root"),
    depth: int = typer.Option(2, "--depth", "-d", help="Recursion depth (reserved)."),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Constructor dependency hints: ``__init__`` parameter names for a class."""
    from repograph.surfaces.api import RepoGraph
    from repograph.settings import repograph_dir

    root, store = _get_root_and_store(path)
    store.close()
    with RepoGraph(root, repograph_dir=repograph_dir(root)) as rg:
        if not rg._is_initialized():
            console.print("[red]Not initialized. Run [bold]repograph sync[/] first.[/]")
            raise typer.Exit(1)
        data = rg.constructor_deps(symbol, depth=depth)
    if as_json:
        console.print(_json.dumps(data, indent=2))
        return

    if "error" in data:
        console.print(f"[yellow]Class '{symbol}' not found.[/] Run [bold]repograph sync[/] first.")
        raise typer.Exit(1)

    params = data.get("parameters") or []
    if not params:
        console.print(
            f"[bold]{data.get('class', symbol)}[/]  [dim]__init__[/]\n"
            f"  [dim]No typed constructor parameters found.[/]\n"
            f"  [dim](Run [bold]repograph sync[/] if the index was built before the HAS_METHOD fix.)[/]"
        )
        return

    # Render a clean dependency tree showing parameter name and type.
    # Parameters without type annotations are shown in dim style.
    console.print(f"\n[bold cyan]{data.get('class', symbol)}[/]  [dim]__init__ dependencies[/]")
    for p in params:
        name = p.get("name", "?") if isinstance(p, dict) else str(p)
        ptype = p.get("type", "") if isinstance(p, dict) else ""
        if ptype:
            console.print(f"  [green]└──[/] [cyan]{name}[/]  [dim]{ptype}[/]")
        else:
            console.print(f"  [green]└──[/] [cyan]{name}[/]  [dim](no annotation)[/]")
    console.print()


# ---------------------------------------------------------------------------
# repograph invariants
# ---------------------------------------------------------------------------

@app.command()
def invariants(
    path: str | None = typer.Argument(None),
    type_filter: str | None = typer.Option(None, "--type", "-t",
        help="Filter by type: constraint | guarantee | thread | lifecycle"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Show architectural invariants documented in docstrings.

    Surfaces constraints like 'NEVER calls X', 'NOT thread-safe', 'MUST be
    started before Y' so AI agents and developers don't accidentally violate them.
    """
    from repograph.surfaces.api import RepoGraph
    from repograph.settings import repograph_dir

    root, store = _get_root_and_store(path)
    store.close()

    with RepoGraph(root, repograph_dir=repograph_dir(root)) as rg:
        items = rg.invariants(inv_type=type_filter)

    if not items:
        if type_filter:
            console.print(f"[yellow]No '{type_filter}' invariants found.[/]")
        else:
            console.print("[yellow]No invariants found.[/] Run [bold]repograph sync[/] first, "
                          "or add INV-/NEVER/MUST NOT annotations to docstrings.")
        raise typer.Exit(0)

    if as_json:
        console.print(_json.dumps(items, indent=2))
        return

    type_order = ["constraint", "guarantee", "thread", "lifecycle"]
    by_type: dict[str, list[dict]] = {t: [] for t in type_order}
    for item in items:
        t = item.get("invariant_type", "constraint")
        by_type.setdefault(t, []).append(item)

    type_colors = {"constraint": "red", "guarantee": "green",
                   "thread": "yellow", "lifecycle": "cyan"}

    console.print(f"\n[bold]Architectural Invariants[/]  ({len(items)} total)\n")
    for t in type_order:
        group = by_type.get(t, [])
        if not group:
            continue
        color = type_colors.get(t, "white")
        console.print(f"[bold {color}]{t.upper()} ({len(group)})[/]")
        for item in group:
            sym = item.get("symbol_name", "?")
            fp = item.get("file_path", "")
            text = item.get("invariant_text", "")
            console.print(f"  [cyan]{sym}[/]  [dim]{fp}[/]")
            console.print(f"    {text}")
        console.print()


# ---------------------------------------------------------------------------
# repograph test-map
# ---------------------------------------------------------------------------

@app.command(name="test-map")
def test_map(
    path: str | None = typer.Argument(None),
    min_eps: int = typer.Option(1, "--min-eps", help="Only show files with at least N entry points."),
    uncovered_only: bool = typer.Option(False, "--uncovered", help="Only show files with 0% coverage."),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON."),
    any_call: bool = typer.Option(
        False,
        "--any-call",
        help=(
            "Count any production function with a test caller, not only Phase-10 "
            "is_entry_point functions — different denominator; closer to 'tests touch this file'."
        ),
    ),
) -> None:
    """Test coverage map: production functions reachable from tests via CALLS.

    Default metric: share of **Phase-10 entry points** per file with a CALLS edge
    from an ``is_test`` function.  Use ``--any-call`` for **all** non-test
    functions in the file (not line or branch coverage).  Files are sorted by
    coverage (least covered first).  0% rows are highlighted in red.
    """
    from repograph.surfaces.api import RepoGraph
    from repograph.settings import repograph_dir

    root, store = _get_root_and_store(path)
    store.close()

    with RepoGraph(root, repograph_dir=repograph_dir(root)) as rg:
        rows = rg.test_coverage_any_call() if any_call else rg.test_coverage()

    if not rows:
        console.print("[yellow]No rows found.[/] Run [bold]repograph sync[/] first.")
        raise typer.Exit(1)

    count_key = "function_count" if any_call else "entry_point_count"
    tested_key = "tested_functions" if any_call else "tested_entry_points"

    if min_eps > 1:
        rows = [r for r in rows if r[count_key] >= min_eps]
    if uncovered_only:
        rows = [r for r in rows if r[tested_key] == 0]

    if as_json:
        console.print(_json.dumps(rows, indent=2))
        return

    tested_count = sum(1 for r in rows if r["coverage_pct"] == 100.0)
    uncovered_count = sum(1 for r in rows if r[tested_key] == 0)
    total_units = sum(r[count_key] for r in rows)
    total_tested = sum(r[tested_key] for r in rows)
    overall_pct = round(total_tested / total_units * 100, 1) if total_units else 0.0

    from repograph.graph_store.store_queries_entrypoints import (
        ANY_CALL_TEST_COVERAGE_DEFINITION,
        ENTRY_POINT_TEST_COVERAGE_DEFINITION,
    )

    label = "functions" if any_call else "entry points"
    defn = ANY_CALL_TEST_COVERAGE_DEFINITION if any_call else ENTRY_POINT_TEST_COVERAGE_DEFINITION

    console.print(f"\n[bold]Test Coverage Map[/]  "
                  f"{total_tested}/{total_units} {label} tested  "
                  f"([{'green' if overall_pct >= 70 else 'yellow' if overall_pct >= 40 else 'red'}]"
                  f"{overall_pct}% overall[/])")
    console.print(f"[dim]{defn}[/]\n")

    table = Table(show_header=True, show_lines=False)
    table.add_column("File", style="cyan", min_width=35)
    col_n = "Fns" if any_call else "EPs"
    table.add_column(col_n, justify="right", style="dim")
    table.add_column("Tested", justify="right")
    table.add_column("Coverage", justify="right")
    table.add_column("Test Files", style="dim", max_width=40)

    for r in rows:
        pct = r["coverage_pct"]
        if pct == 0.0:
            pct_str = "[red]0%[/]"
        elif pct < 50.0:
            pct_str = f"[yellow]{pct:.0f}%[/]"
        elif pct < 100.0:
            pct_str = f"[cyan]{pct:.0f}%[/]"
        else:
            pct_str = "[green]100%[/]"

        tf = r.get("test_files", [])
        tf_str = ", ".join(t.split("/")[-1] for t in tf[:2])
        if len(tf) > 2:
            tf_str += f" +{len(tf)-2}"

        table.add_row(
            r["file_path"],
            str(r[count_key]),
            str(r[tested_key]),
            pct_str,
            tf_str or "[dim]none[/]",
        )

    console.print(table)
    console.print(
        f"\n[dim]{len(rows)} files · {uncovered_count} with no test coverage · "
        f"{tested_count} fully covered[/]"
    )
