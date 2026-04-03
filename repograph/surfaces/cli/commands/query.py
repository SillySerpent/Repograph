"""Query commands: node, query, impact, impact-graph, diff-impact."""
from __future__ import annotations

import subprocess

import typer
from rich.panel import Panel
from rich.table import Table

from repograph.services.symbol_resolution import resolve_identifier
from repograph.surfaces.cli.app import app, console, _get_root_and_store


# ---------------------------------------------------------------------------
# repograph node
# ---------------------------------------------------------------------------


def _print_ambiguous_matches(identifier: str, matches: list[dict], *, strategy: str) -> None:
    table = Table(title=f"Ambiguous match for '{identifier}'")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Function", style="cyan")
    table.add_column("File", style="white")
    table.add_column("Signature", style="dim")
    for index, match in enumerate(matches, start=1):
        table.add_row(
            str(index),
            match.get("qualified_name", "?"),
            match.get("file_path", "?"),
            match.get("signature", "") or "—",
        )
    console.print(table)
    console.print(
        f"[yellow]Multiple matches found via {strategy}.[/] "
        "Retry with an exact qualified name."
    )

@app.command()
def node(
    identifier: str = typer.Argument(..., help="File path or symbol qualified name"),
    path: str | None = typer.Option(None, "--path"),
):
    """Show structured truth for a file or symbol."""
    root, store = _get_root_and_store(path)
    resolution = resolve_identifier(store, identifier, limit=5)

    if resolution["kind"] == "file":
        file_info = resolution["match"]
        file_path = file_info.get("path", identifier)
        functions = store.get_functions_in_file(file_path)
        table = Table(title=f"File: {file_path}")
        table.add_column("Function", style="cyan")
        table.add_column("Lines")
        table.add_column("Entry", justify="center")
        table.add_column("Dead", justify="center")
        for fn in functions:
            table.add_row(
                fn["qualified_name"],
                f"{fn['line_start']}–{fn['line_end']}",
                "✓" if fn.get("is_entry_point") else "",
                "✗" if fn.get("is_dead") else "",
            )
        console.print(table)
        return

    if resolution["kind"] == "ambiguous":
        _print_ambiguous_matches(
            identifier,
            resolution["matches"],
            strategy=resolution["strategy"],
        )
        raise typer.Exit(2)

    if resolution["kind"] == "not_found":
        console.print(f"[red]No file or symbol found for '{identifier}'[/]")
        raise typer.Exit(1)

    fn_info = resolution["match"]
    fn = store.get_function_by_id(fn_info["id"])
    if not fn:
        console.print(f"[red]No file or symbol found for '{identifier}'[/]")
        raise typer.Exit(1)
    callers = store.get_callers(fn["id"])
    callees = store.get_callees(fn["id"])
    console.print(Panel(
        f"[bold]{fn['qualified_name']}[/]\n"
        f"Resolution: {resolution['strategy']}\n"
        f"File: {fn['file_path']} : {fn['line_start']}–{fn['line_end']}\n"
        f"Signature: {fn['signature']}\n"
        f"Entry point: {fn.get('is_entry_point', False)}  Dead: {fn.get('is_dead', False)}\n"
        f"Callers ({len(callers)}): {', '.join(c['qualified_name'].split(':')[-1] for c in callers[:5])}\n"
        f"Callees ({len(callees)}): {', '.join(c['qualified_name'].split(':')[-1] for c in callees[:5])}",
        title=f"node: {fn['name']}",
    ))


# ---------------------------------------------------------------------------
# repograph query
# ---------------------------------------------------------------------------

@app.command()
def query(
    text: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(10, "--limit", "-n"),
    path: str | None = typer.Option(None, "--path"),
):
    """Hybrid search over functions and pathways."""
    root, store = _get_root_and_store(path)
    from repograph.search.hybrid import HybridSearch

    searcher = HybridSearch(store)
    results = searcher.search(text, limit=limit)

    if not results:
        console.print(f"[yellow]No results for '{text}'[/]")
        return

    table = Table(title=f"Search: {text}")
    table.add_column("Score", justify="right")
    table.add_column("Type", style="dim")
    table.add_column("Name", style="cyan")
    table.add_column("File")
    for r in results:
        table.add_row(
            f"{r.get('score', 0.0):.2f}",
            r.get("type", "?"),
            r.get("name", "?"),
            r.get("file_path", "?"),
        )
    console.print(table)


# ---------------------------------------------------------------------------
# repograph impact
# ---------------------------------------------------------------------------

@app.command()
def impact(
    symbol: str = typer.Argument(..., help="Symbol name or qualified name"),
    depth: int = typer.Option(3, "--depth", "-d"),
    path: str | None = typer.Option(None, "--path"),
):
    """Blast radius: everything that calls or imports this symbol."""
    root, store = _get_root_and_store(path)
    resolution = resolve_identifier(store, symbol, limit=5)

    if resolution["kind"] == "not_found":
        console.print(f"[red]Symbol '{symbol}' not found.[/]")
        raise typer.Exit(1)
    if resolution["kind"] == "file":
        console.print(f"[red]Expected a symbol, got a file path: '{symbol}'[/]")
        raise typer.Exit(1)
    if resolution["kind"] == "ambiguous":
        _print_ambiguous_matches(symbol, resolution["matches"], strategy=resolution["strategy"])
        raise typer.Exit(2)

    fn_id = resolution["match"]["id"]
    fn = store.get_function_by_id(fn_id)
    if not fn:
        raise typer.Exit(1)

    # BFS upward through callers
    visited: dict[str, dict] = {}
    level_map: dict[str, int] = {}
    queue = [(fn_id, 0)]
    while queue:
        cur_id, cur_depth = queue.pop(0)
        if cur_id in visited or cur_depth > depth:
            continue
        visited[cur_id] = store.get_function_by_id(cur_id) or {}
        level_map[cur_id] = cur_depth
        for caller in store.get_callers(cur_id):
            if caller["id"] not in visited:
                queue.append((caller["id"], cur_depth + 1))

    # Remove the target itself
    visited.pop(fn_id, None)

    if not visited:
        console.print(f"[green]'{symbol}' has no callers — safe to change.[/]")
        return

    table = Table(title=f"Impact of changing '{symbol}'")
    table.add_column("Depth", justify="right")
    table.add_column("Caller", style="cyan")
    table.add_column("File")
    for fid, info in sorted(visited.items(), key=lambda x: level_map.get(x[0], 0)):
        table.add_row(
            str(level_map.get(fid, "?")),
            info.get("qualified_name", "?"),
            info.get("file_path", "?"),
        )
    console.print(table)


# ---------------------------------------------------------------------------
# repograph impact-graph  (I3)
# ---------------------------------------------------------------------------

@app.command("impact-graph")
def impact_graph(
    entry: str = typer.Argument(..., help="Entry point: qualified name or function ID"),
    fmt: str = typer.Option("mermaid", "--format", "-f", help="Output format: mermaid | dot"),
    depth: int = typer.Option(4, "--depth", "-d", help="Maximum call-graph depth"),
    min_conf: float = typer.Option(0.5, "--min-conf", help="Minimum edge confidence (0–1)"),
    out: str | None = typer.Option(None, "--out", "-o", help="Write diagram to file instead of stdout"),
    path: str | None = typer.Option(None, "--path"),
):
    """Render a confidence-weighted call graph centred on an entry point.

    \\b
    Examples:
      repograph impact-graph my_module.my_func
      repograph impact-graph my_func --format dot --depth 3 --out graph.dot
      repograph impact-graph my_func --format mermaid | pbcopy
    """
    _root, store = _get_root_and_store(path)

    from repograph.plugins.exporters.impact_graph.plugin import render_impact_graph

    diagram, n_nodes, n_edges = render_impact_graph(
        store,
        entry_point=entry,
        fmt=fmt,
        max_depth=depth,
        min_confidence=min_conf,
    )

    if not diagram:
        console.print(f"[red]Entry point '{entry}' not found or no callees.[/]")
        raise typer.Exit(1)

    if out:
        import pathlib
        pathlib.Path(out).write_text(diagram, encoding="utf-8")
        console.print(f"[green]Wrote {fmt} diagram ({n_nodes} nodes, {n_edges} edges) to {out}[/]")
    else:
        console.print(diagram)
        console.print(
            f"\n[dim]({n_nodes} nodes, {n_edges} edges, format={fmt})[/]",
            highlight=False,
        )


# ---------------------------------------------------------------------------
# repograph diff-impact  (I1)
# ---------------------------------------------------------------------------

@app.command("diff-impact")
def diff_impact(
    diff: str | None = typer.Option(
        None, "--diff", "-d",
        help="Git ref to diff against (e.g. HEAD~1, main). "
             "Changed file paths are resolved via `git diff --name-only`.",
    ),
    files: list[str] | None = typer.Option(
        None, "--files", "-f",
        help="Explicit list of changed file paths (relative to repo root). "
             "Mutually exclusive with --diff.",
    ),
    max_hops: int = typer.Option(5, "--hops", help="Maximum call-graph hops."),
    path: str | None = typer.Option(None, "--path"),
):
    """Rank all functions affected by a set of file changes.

    Uses the call graph (plus MAKES_HTTP_CALL edges for cross-language impact)
    to compute transitive callers of every function in the changed files, scored
    by entry_score × hop_decay.

    \\b
    Examples:
      repograph diff-impact --diff HEAD~1
      repograph diff-impact --diff main
      repograph diff-impact --files app/models/user.py app/auth.py
    """
    root, store = _get_root_and_store(path)

    if diff and files:
        console.print("[red]--diff and --files are mutually exclusive.[/]")
        raise typer.Exit(1)

    if diff:
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", diff],
                capture_output=True, text=True, check=True, cwd=root,
            )
            changed = [p.strip() for p in result.stdout.splitlines() if p.strip()]
        except subprocess.CalledProcessError as exc:
            console.print(f"[red]git diff failed: {exc.stderr.strip()}[/]")
            raise typer.Exit(1)
    elif files:
        changed = list(files)
    else:
        console.print("[red]Provide --diff <git-ref> or --files <paths>.[/]")
        raise typer.Exit(1)

    if not changed:
        console.print("[green]No changed files found.[/]")
        return

    from repograph.services.impact_analysis import compute_impact, format_impact_table

    console.print(f"[cyan]Analyzing impact of {len(changed)} changed file(s)...[/]")
    results = compute_impact(store, changed_paths=changed, max_hops=max_hops)

    if not results:
        console.print("[green]No callers found for the changed files.[/]")
        return

    table = Table(title=f"Impact analysis ({len(results)} affected functions)")
    table.add_column("Score", justify="right", style="yellow")
    table.add_column("Hop", justify="right")
    table.add_column("HTTP", justify="center")
    table.add_column("Function", style="cyan")
    table.add_column("File")

    for r in results[:50]:
        table.add_row(
            f"{r.impact_score:.3f}",
            str(r.hop),
            "✓" if r.via_http else "",
            r.qualified_name,
            r.file_path,
        )
    if len(results) > 50:
        table.add_row("...", "...", "...", f"...and {len(results) - 50} more", "")

    console.print(table)
