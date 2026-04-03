"""Modules CLI command."""
from __future__ import annotations

import json as _json

import typer
from rich import box as _box
from rich.table import Table

from repograph.surfaces.cli.app import app, console, _get_service


@app.command()
def modules(
    path: str | None = typer.Argument(None),
    min_files: int = typer.Option(1, "--min-files", "-m", help="Hide modules with fewer than N files."),
    issues_only: bool = typer.Option(False, "--issues", help="Only show modules with dead code or duplicates."),
    as_json: bool = typer.Option(False, "--json", help="Output as machine-readable JSON."),
) -> None:
    """Module map: per-directory overview of classes, coverage, and issues.

    A single call gives a structural map of the entire repository — replaces
    calling 'node' on every file individually when doing context-gathering.
    """
    _, rg = _get_service(path)
    with rg:
        mod_list = rg.modules()

    if not mod_list:
        console.print("[yellow]Module index not found.[/] Run [bold]repograph sync[/] to build it.")
        raise typer.Exit(1)

    if min_files > 1:
        mod_list = [
            module for module in mod_list
            if module.get("prod_file_count", module.get("file_count", 0)) >= min_files
        ]
    if issues_only:
        mod_list = [
            module for module in mod_list
            if module["dead_code_count"] > 0 or module["duplicate_count"] > 0
        ]

    if as_json:
        import sys

        sys.stdout.write(_json.dumps(mod_list, indent=2, ensure_ascii=False))
        sys.stdout.write("\n")
        return

    table = Table(title="Module Map", show_header=True, header_style="bold dim", box=_box.SIMPLE)
    table.add_column("Module", style="cyan", min_width=20)
    table.add_column("Src/Test", justify="right", style="dim")
    table.add_column("Fn", justify="right", style="dim")
    table.add_column("Cls", justify="right", style="dim")
    table.add_column("Key Classes", style="white", max_width=36)
    table.add_column("TstFn", justify="right", style="dim")
    table.add_column("Issues", justify="right")

    prod = [module for module in mod_list if module.get("category", "production") != "tooling"]
    tool = [module for module in mod_list if module.get("category") == "tooling"]

    def _src_test(module: dict) -> str:
        src = module.get("prod_file_count", module.get("file_count", 0))
        tst = module.get("test_file_count", 0)
        return f"{src}/{tst}"

    def _add_rows(tbl: Table, rows: list[dict]) -> None:
        for module in rows:
            issue_parts = []
            if module["dead_code_count"]:
                issue_parts.append(f"[red]{module['dead_code_count']} dead[/]")
            if module["duplicate_count"]:
                issue_parts.append(f"[yellow]{module['duplicate_count']} dup[/]")
            issue_str = "  ".join(issue_parts) if issue_parts else "[green]—[/]"
            tst_fn = module.get("test_function_count", 0)
            key_cls = ", ".join(module["key_classes"][:3])
            if len(module["key_classes"]) > 3:
                key_cls += f"… +{len(module['key_classes']) - 3}"
            tbl.add_row(
                module["display"],
                _src_test(module),
                str(module["function_count"]),
                str(module.get("class_count", 0)),
                key_cls or "[dim]—[/]",
                str(tst_fn) if tst_fn else "[dim]—[/]",
                issue_str,
            )

    _add_rows(table, prod)
    console.print(table)
    if tool:
        console.print("\n[bold dim]Tooling & scripts[/]")
        tooling_table = Table(title=None, show_header=True, header_style="bold dim", box=_box.SIMPLE)
        tooling_table.add_column("Module", style="cyan", min_width=20)
        tooling_table.add_column("Src/Test", justify="right", style="dim")
        tooling_table.add_column("Fn", justify="right", style="dim")
        tooling_table.add_column("Cls", justify="right", style="dim")
        tooling_table.add_column("Key Classes", style="white", max_width=36)
        tooling_table.add_column("TstFn", justify="right", style="dim")
        tooling_table.add_column("Issues", justify="right")
        _add_rows(tooling_table, tool)
        console.print(tooling_table)

    console.print(
        f"\n[dim]{len(mod_list)} modules shown.[/] "
        "Use [bold]--issues[/] to filter, [bold]--json[/] for full data."
    )
