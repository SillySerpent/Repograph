"""Admin commands: doctor, config-registry."""
from __future__ import annotations

import json as _json

import typer
from rich.table import Table

from repograph.surfaces.cli.app import app, console, _cli_command_session, _get_root_and_store


# ---------------------------------------------------------------------------
# repograph doctor
# ---------------------------------------------------------------------------

@app.command()
def doctor(
    path: str | None = typer.Argument(None, help="Repo root (tests DB open if initialized)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show pip show repograph"),
):
    """Verify Python environment, imports, and optional graph database."""
    from repograph.diagnostics.env_doctor import run_doctor

    with _cli_command_session(path, command="doctor"):
        run_doctor(repo_path=path, verbose=verbose)


# ---------------------------------------------------------------------------
# repograph config-registry  (formerly "config")
# ---------------------------------------------------------------------------

@app.command(name="config-registry")
def config_registry_cmd(
    path: str | None = typer.Argument(None),
    key: str | None = typer.Option(None, "--key", "-k", help="Show consumers of a single config key."),
    top: int = typer.Option(20, "--top", "-n", help="Number of keys to show (default 20)."),
    as_json: bool = typer.Option(False, "--json", help="Output as machine-readable JSON."),
    include_tests: bool = typer.Option(
        False,
        "--include-tests",
        help="Rebuild registry from the graph including test files (live scan; ignores cached JSON).",
    ),
) -> None:
    """Config key map: which pathways and files read each config value.

    Use --key <name> to see the full blast radius of a single key rename.
    """
    from repograph.surfaces.api import RepoGraph
    from repograph.settings import repograph_dir

    with _cli_command_session(path, command="config-registry"):
        root, store = _get_root_and_store(path)

        if include_tests:
            from repograph.plugins.exporters.config_registry.plugin import build_registry

            registry = build_registry(store, include_tests=True)
            store.close()
            if key is not None:
                registry = {key: registry[key]} if key in registry else {}
        else:
            store.close()
            with RepoGraph(root, repograph_dir=repograph_dir(root)) as rg:
                registry = rg.config_registry(key=key)

        if not registry:
            if key:
                console.print(f"[yellow]Config key '{key}' not found in registry.[/]")
            else:
                console.print("[yellow]Config registry not found.[/] Run [bold]repograph sync[/] first.")
            raise typer.Exit(1)

        if as_json:
            console.print(_json.dumps(registry, indent=2))
            return

        if key:
            # Single key detail view
            data = registry.get(key, {})
            console.print(f"\n[bold cyan]Config key:[/] {key}")
            console.print(f"[bold]Usage count:[/] {data.get('usage_count', 0)}\n")
            pathways = data.get("pathways", [])
            if pathways:
                console.print("[bold]Used by pathways:[/]")
                for pw in pathways:
                    console.print(f"  • {pw}")
            files = data.get("files", [])
            if files:
                console.print(f"\n[bold]Read in files ({len(files)}):[/]")
                for fp in files[:20]:
                    console.print(f"  {fp}")
                if len(files) > 20:
                    console.print(f"  [dim]… and {len(files) - 20} more[/]")
            return

        # Split into top-level keys and dotted-path keys so granular entries
        # (e.g. market.symbol) don't get buried below shallow aggregate keys
        # that happen to have higher raw usage counts (e.g. market: 12 usages).
        top_level = [(k, v) for k, v in registry.items() if "." not in k]
        dotted = [(k, v) for k, v in registry.items() if "." in k]

        def _registry_table(title: str, items: list) -> None:
            if not items:
                return
            t = Table(title=title, show_header=True)
            t.add_column("Config Key", style="cyan", min_width=28)
            t.add_column("Usage", justify="right", style="dim")
            t.add_column("Pathways", justify="right")
            t.add_column("Files", justify="right")
            t.add_column("Sample Pathways", style="dim", max_width=40)
            for k, data in items[:top]:
                pw_list = data.get("pathways", [])
                sample = ", ".join(pw_list[:2])
                if len(pw_list) > 2:
                    sample += f" +{len(pw_list)-2}"
                t.add_row(
                    k,
                    str(data.get("usage_count", 0)),
                    str(len(pw_list)),
                    str(len(data.get("files", []))),
                    sample or "[dim]—[/]",
                )
            console.print(t)

        _registry_table(
            f"Top-Level Config Keys  (top {min(top, len(top_level))} of {len(top_level)})",
            top_level,
        )
        if dotted:
            _registry_table(
                f"Dotted Config Keys  ({len(dotted)} granular paths)",
                sorted(dotted, key=lambda x: -x[1]["usage_count"]),
            )
        total = len(registry)
        console.print(
            f"\n[dim]{total} config keys total "
            f"({len(top_level)} top-level, {len(dotted)} dotted). "
            f"Use [bold]--key <n>[/] for blast-radius detail.[/]"
        )
