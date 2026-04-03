"""Pathway CLI commands."""
from __future__ import annotations

import typer
from rich import box as _box
from rich.panel import Panel
from rich.table import Table

from repograph.surfaces.cli.app import console, pathway_app, _get_root_and_store, _get_service


@pathway_app.command("list")
def pathway_list(
    path: str | None = typer.Argument(None),
    include_tests: bool = typer.Option(
        False, "--include-tests",
        help="Include auto-detected test pathways in the list.",
    ),
):
    """List all pathways with confidence and step count.

    By default only production pathways are shown. Pass --include-tests
    to also see test-entry pathways.
    """
    _, rg = _get_service(path)
    with rg:
        all_pathways = rg.pathways(min_confidence=0.0, include_tests=True)

    if not all_pathways:
        console.print("[yellow]No pathways found. Run [bold]repograph sync[/] first.[/]")
        raise typer.Exit(0)

    prod = [pathway for pathway in all_pathways if pathway.get("source") != "auto_detected_test"]
    tests = [pathway for pathway in all_pathways if pathway.get("source") == "auto_detected_test"]

    def _render_table(pathways: list[dict], title: str) -> None:
        table = Table(title=title, show_header=True, header_style="bold dim", box=_box.SIMPLE)
        table.add_column("Name", style="cyan")
        table.add_column("Display Name")
        table.add_column("Steps", justify="right")
        table.add_column("Importance", justify="right")
        table.add_column("Confidence", justify="right")
        table.add_column("Source", style="dim")
        sorted_pathways = sorted(
            pathways,
            key=lambda item: (-(item.get("importance_score") or 0.0), -(item.get("confidence") or 0.0)),
        )
        for pathway in sorted_pathways:
            conf = pathway.get("confidence") or 0.0
            color = "green" if conf >= 0.8 else "yellow" if conf >= 0.5 else "red"
            table.add_row(
                pathway["name"],
                pathway.get("display_name") or pathway["name"],
                str(pathway.get("step_count") or 0),
                f"{(pathway.get('importance_score') or 0.0):.2f}",
                f"[{color}]{conf:.2f}[/]",
                pathway.get("source") or "auto",
            )
        console.print(table)

    _render_table(prod, f"Pathways ({len(prod)} production)")
    if tests:
        if include_tests:
            _render_table(tests, f"Test pathways ({len(tests)})")
        else:
            console.print(
                f"[dim]{len(tests)} test pathway(s) hidden "
                f"— pass [bold]--include-tests[/] to show them.[/]"
            )


@pathway_app.command("show")
def pathway_show(
    name: str = typer.Argument(..., help="Pathway name"),
    path: str | None = typer.Argument(None, help="Repo path (defaults to cwd)"),
):
    """Print the full context document for a pathway."""
    _, store = _get_root_and_store(path)
    pathway = store.get_pathway(name)

    if not pathway:
        console.print(f"[red]Pathway '{name}' not found.[/]")
        console.print("Run [bold]repograph pathway list[/] to see available pathways.")
        raise typer.Exit(1)

    ctx = pathway.get("context_doc") or ""
    if not ctx:
        from repograph.plugins.exporters.pathway_contexts.generator import generate_pathway_context

        ctx = generate_pathway_context(pathway["id"], store)

    if ctx:
        console.print(ctx)
    else:
        console.print(Panel(
            f"[bold]{pathway.get('display_name') or name}[/]\n\n"
            f"Entry: {pathway.get('entry_function', '?')}\n"
            f"Steps: {pathway.get('step_count', 0)}\n"
            f"Confidence: {pathway.get('confidence', 0.0):.2f}",
            title=f"pathway: {name}",
        ))


@pathway_app.command("update")
def pathway_update(
    name: str = typer.Argument(..., help="Pathway name"),
    path: str | None = typer.Option(None, "--path"),
):
    """Re-generate context document for a single pathway."""
    root, store = _get_root_and_store(path)
    from repograph.plugins.exporters.pathway_contexts.generator import generate_pathway_context
    from repograph.plugins.static_analyzers.pathways.assembler import PathwayAssembler
    from repograph.plugins.static_analyzers.pathways.curator import PathwayCurator

    pathway = store.get_pathway(name)
    if not pathway:
        console.print(f"[red]Pathway '{name}' not found.[/]")
        raise typer.Exit(1)

    curator = PathwayCurator(root)
    assembler = PathwayAssembler(store)
    ep_id = pathway.get("id", "").replace("pathway:", "", 1)
    curated = curator.get(name)

    doc = assembler.assemble(ep_id, curated_def=curated)
    if doc:
        store.upsert_pathway(doc)
        for step in doc.steps:
            store.insert_step_in_pathway(step.function_id, doc.id, step.order, step.role)

    ctx = generate_pathway_context(pathway["id"], store)
    if ctx:
        console.print(f"[green]✓ Updated context doc for '{name}' ({len(ctx)} chars)[/]")
    else:
        console.print(f"[yellow]Could not generate context for '{name}'[/]")
