"""Settings management commands: repograph config get/set/list/describe/unset/reset."""
from __future__ import annotations

import json as _json

import typer
from rich.panel import Panel
from rich.table import Table

from repograph.surfaces.cli.app import app, console

config_app = typer.Typer(
    name="config",
    help="Manage RepoGraph settings and runtime overrides stored in .repograph/settings.json.",
)
app.add_typer(config_app, name="config")


def _format_value(value) -> str:
    if isinstance(value, (list, dict, bool)) or value is None:
        return _json.dumps(value)
    return str(value)


@config_app.command("list")
def config_list(
    path: str | None = typer.Argument(None, help="Repo root (default: cwd)"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show all current settings and their effective values."""
    import os
    import sys
    from repograph.settings import ensure_settings_file, load_settings, get_repo_root, list_setting_metadata
    from repograph.exceptions import RepographNotFoundError
    from dataclasses import asdict

    try:
        root = get_repo_root(path)
    except RepographNotFoundError:
        root = os.path.abspath(path or os.getcwd())

    ensure_settings_file(root)
    settings = load_settings(root)
    data = asdict(settings)

    if as_json:
        sys.stdout.write(_json.dumps(data, indent=2))
        sys.stdout.write("\n")
        return

    metadata = {item["key"]: item for item in list_setting_metadata(root)}
    table = Table(title="RepoGraph Settings", show_header=True)
    table.add_column("Key", style="cyan", min_width=28)
    table.add_column("Current", style="green")
    table.add_column("Default", style="dim")
    table.add_column("Source", style="blue")
    table.add_column("Takes Effect", style="magenta")
    for key, val in sorted(data.items()):
        meta = metadata[key]
        table.add_row(
            key,
            _format_value(val),
            _format_value(meta["default"]),
            str(meta.get("source", "default")),
            str(meta["takes_effect"]),
        )
    console.print(table)
    console.print(
        f"\n[dim]Open [bold]{root}/.repograph/settings.json[/bold] to inspect the live effective values, "
        "editable runtime overrides, and per-setting schema metadata. "
        "Use [bold]repograph config describe KEY[/bold] for one setting at a time.[/]"
    )


@config_app.command("get")
def config_get(
    key: str = typer.Argument(..., help="Setting name"),
    path: str | None = typer.Option(None, "--path", help="Repo root"),
) -> None:
    """Show the current value of a setting."""
    import os
    from repograph.settings import get_setting, get_repo_root
    from repograph.exceptions import RepographNotFoundError

    try:
        root = get_repo_root(path)
    except RepographNotFoundError:
        root = os.path.abspath(path or os.getcwd())

    try:
        value = get_setting(root, key)
        console.print(f"[cyan]{key}[/] = [green]{_json.dumps(value) if isinstance(value, (list, dict, bool)) else value}[/]")
    except KeyError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Setting name"),
    value: str = typer.Argument(..., help="New value (JSON for lists/booleans, plain string otherwise)"),
    path: str | None = typer.Option(None, "--path", help="Repo root"),
) -> None:
    """Persist a setting change to .repograph/settings.json.

    Value is parsed as JSON first, then as a plain string.

    \\b
    Examples:
      repograph config set auto_dynamic_analysis false
      repograph config set exclude_dirs '["vendor","dist"]'
      repograph config set nl_model claude-opus-4-6
    """
    import os
    from repograph.settings import set_setting, get_repo_root
    from repograph.exceptions import RepographNotFoundError

    try:
        root = get_repo_root(path)
    except RepographNotFoundError:
        root = os.path.abspath(path or os.getcwd())

    try:
        parsed = _json.loads(value)
    except (ValueError, TypeError):
        parsed = value

    try:
        set_setting(root, key, parsed)
        console.print(f"[green]✓[/] [cyan]{key}[/] = [bold]{_format_value(parsed)}[/]")
        console.print(f"[dim]Saved to {root}/.repograph/settings.json[/]")
    except (KeyError, ValueError) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)


@config_app.command("describe")
def config_describe(
    key: str | None = typer.Argument(None, help="Setting name (omit to show the full schema summary)"),
    path: str | None = typer.Option(None, "--path", help="Repo root"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show schema, default, current value, and lifecycle details for settings."""
    import os
    import sys
    from repograph.settings import (
        describe_setting,
        ensure_settings_file,
        get_repo_root,
        list_setting_metadata,
    )
    from repograph.exceptions import RepographNotFoundError

    try:
        root = get_repo_root(path)
    except RepographNotFoundError:
        root = os.path.abspath(path or os.getcwd())

    ensure_settings_file(root)

    if key is None:
        rows = list_setting_metadata(root)
        if as_json:
            sys.stdout.write(_json.dumps(rows, indent=2))
            sys.stdout.write("\n")
            return
        table = Table(title="RepoGraph Setting Schema", show_header=True)
        table.add_column("Key", style="cyan", min_width=28)
        table.add_column("Type", style="magenta")
        table.add_column("Current", style="green")
        table.add_column("Default", style="dim")
        table.add_column("Source", style="blue")
        table.add_column("Takes Effect", style="yellow")
        for row in rows:
            table.add_row(
                row["key"],
                row["type"],
                _format_value(row["current"]),
                _format_value(row["default"]),
                str(row.get("source", "default")),
                row["takes_effect"],
            )
        console.print(table)
        console.print(
            "[dim]Use [bold]repograph config describe KEY[/bold] for source, value-shape, and lifecycle details for one setting.[/]"
        )
        return

    try:
        info = describe_setting(root, key)
    except KeyError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)

    if as_json:
        sys.stdout.write(_json.dumps(info, indent=2))
        sys.stdout.write("\n")
        return

    body = Table(show_header=False, box=None, padding=(0, 1))
    body.add_column("Field", style="cyan", min_width=18)
    body.add_column("Value", style="white")
    body.add_row("Key", info["key"])
    body.add_row("Type", info["type"])
    body.add_row("Value Shape", info["value_shape"])
    body.add_row("Current", _format_value(info["current"]))
    body.add_row("Default", _format_value(info["default"]))
    body.add_row("Source", str(info.get("source", "default")))
    body.add_row("Takes Effect", info["takes_effect"])
    body.add_row("Requires Reindex", "yes" if info["requires_reindex"] else "no")
    body.add_row("Requires Full Sync", "yes" if info["requires_full_sync"] else "no")
    body.add_row("Runtime Only", "yes" if info["affects_runtime_only"] else "no")
    body.add_row("Stability", info["stability"])
    if info.get("allowed_values") is not None:
        body.add_row("Allowed Values", _format_value(info["allowed_values"]))
    if info.get("examples"):
        body.add_row("Examples", _format_value(info["examples"]))
    body.add_row("Description", info["description"])
    console.print(Panel(body, title=f"Setting: {info['key']}", border_style="cyan"))


@config_app.command("unset")
def config_unset(
    key: str = typer.Argument(..., help="Setting name"),
    path: str | None = typer.Option(None, "--path", help="Repo root"),
) -> None:
    """Remove one runtime override so YAML/default values apply again."""
    import os
    from repograph.settings import unset_setting, get_repo_root
    from repograph.exceptions import RepographNotFoundError

    try:
        root = get_repo_root(path)
    except RepographNotFoundError:
        root = os.path.abspath(path or os.getcwd())

    try:
        unset_setting(root, key)
        console.print(f"[green]✓[/] Cleared runtime override for [cyan]{key}[/].")
        console.print("[dim]The effective value now falls back to YAML overrides or the built-in default.[/]")
    except KeyError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)


@config_app.command("reset")
def config_reset(
    path: str | None = typer.Argument(None, help="Repo root (default: cwd)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Clear all runtime overrides and refresh the self-describing settings file."""
    import os
    from repograph.settings import reset_settings, get_repo_root
    from repograph.exceptions import RepographNotFoundError

    try:
        root = get_repo_root(path)
    except RepographNotFoundError:
        root = os.path.abspath(path or os.getcwd())

    if not yes:
        typer.confirm("Clear all runtime setting overrides?", abort=True)

    reset_settings(root)
    console.print("[green]✓ Runtime overrides cleared.[/]")
    console.print(f"[dim]Refreshed settings document at {root}/.repograph/settings.json[/]")
