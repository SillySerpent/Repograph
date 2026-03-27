"""CLI commands for browsing and filtering structured observability logs.

All commands read static JSONL files from ``.repograph/logs/`` and require
no running process.  Output is Rich-formatted for readability.

Registered as the ``logs`` sub-command group in ``repograph.cli``.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from repograph.observability import get_logger

_logger = get_logger(__name__, subsystem="cli")
console = Console()

logs_app = typer.Typer(
    name="logs",
    help="Browse and filter structured observability logs.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _log_dir(repo_path: str | None) -> Path:
    from repograph.config import get_repo_root, repograph_dir
    root = get_repo_root(repo_path)
    return Path(repograph_dir(root)) / "logs"


def _resolve_run_dir(log_dir: Path, run_id: str | None) -> Path | None:
    """Return the run directory — latest symlink if run_id is None."""
    if not log_dir.exists():
        return None
    if run_id:
        candidate = log_dir / run_id
        return candidate if candidate.is_dir() else None
    latest = log_dir / "latest"
    if latest.is_symlink() and latest.exists():
        return latest.resolve()
    # Fall back to most recent by mtime
    dirs = sorted(
        (d for d in log_dir.iterdir() if d.is_dir() and not d.name == "latest"),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    return dirs[0] if dirs else None


def _read_jsonl(path: Path, *, limit: int = 0) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    records = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return records[-limit:] if limit else records


def _level_color(level: str) -> str:
    return {"DEBUG": "dim", "INFO": "green", "WARNING": "yellow", "ERROR": "red", "CRITICAL": "bold red"}.get(
        level.upper(), "white"
    )


def _print_records(records: list[dict], *, max_rows: int = 200) -> None:
    if not records:
        console.print("[dim]No records found.[/]")
        return

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Time", style="dim", no_wrap=True)
    table.add_column("Lvl", no_wrap=True)
    table.add_column("Subsystem", style="cyan", no_wrap=True)
    table.add_column("Message")
    table.add_column("Extra", style="dim")

    shown = records[-max_rows:]
    if len(records) > max_rows:
        console.print(f"[dim](showing last {max_rows} of {len(records)} records)[/]")

    for r in shown:
        ts = r.get("ts", "")
        # Shorten ISO timestamp to HH:MM:SS
        ts_short = ts[11:19] if len(ts) >= 19 else ts
        level = r.get("level", "")
        color = _level_color(level)
        lvl_text = Text(level[:4], style=color)

        subsystem = r.get("subsystem") or ""
        msg = r.get("msg", "")

        # Collect notable extra fields into a short annotation
        extras = []
        for key in ("phase", "plugin_id", "hook", "path", "symbol", "operation"):
            val = r.get(key)
            if val:
                extras.append(f"{key}={val!r}")
        if r.get("exc_type"):
            extras.append(f"exc={r['exc_type']}")
        if r.get("degraded"):
            extras.append("degraded=true")

        table.add_row(ts_short, lvl_text, subsystem, msg, " ".join(extras))

    console.print(table)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@logs_app.command("list")
def logs_list(
    path: Optional[str] = typer.Option(None, "--path", "-p", help="Repo path"),
) -> None:
    """List recent run sessions with run_id, timestamp, and record counts."""
    log_dir = _log_dir(path)
    if not log_dir.exists():
        console.print("[yellow]No log directory found.[/] Run [bold]repograph sync[/] first.")
        raise typer.Exit(0)

    runs = sorted(
        (d for d in log_dir.iterdir() if d.is_dir() and not d.name.startswith(".")),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    if not runs:
        console.print("[dim]No log sessions found.[/]")
        raise typer.Exit(0)

    latest_sym = log_dir / "latest"
    latest_target = latest_sym.resolve() if latest_sym.is_symlink() else None

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Run ID", style="cyan")
    table.add_column("Timestamp")
    table.add_column("Records")
    table.add_column("Errors")
    table.add_column("")

    for run_dir in runs[:20]:  # cap at 20 most recent
        mtime = run_dir.stat().st_mtime
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))

        all_jsonl = run_dir / "all.jsonl"
        err_jsonl = run_dir / "errors.jsonl"
        n_all = len(_read_jsonl(all_jsonl)) if all_jsonl.exists() else 0
        n_err = len(_read_jsonl(err_jsonl)) if err_jsonl.exists() else 0

        tag = "[bold green]← latest[/]" if run_dir.resolve() == latest_target else ""
        err_display = f"[red]{n_err}[/]" if n_err else str(n_err)

        table.add_row(run_dir.name, ts, str(n_all), err_display, tag)

    console.print(table)


@logs_app.command("show")
def logs_show(
    run: Optional[str] = typer.Option(None, "--run", help="Run ID (default: latest)"),
    path: Optional[str] = typer.Option(None, "--path", "-p", help="Repo path"),
    limit: int = typer.Option(100, "--limit", "-n", help="Max records to show"),
) -> None:
    """Show all log records for a run (most recent by default)."""
    log_dir = _log_dir(path)
    run_dir = _resolve_run_dir(log_dir, run)
    if run_dir is None:
        console.print("[red]No log session found.[/] Run [bold]repograph logs list[/] to see available sessions.")
        raise typer.Exit(1)

    console.print(f"[dim]Session:[/] [cyan]{run_dir.name}[/]")
    records = _read_jsonl(run_dir / "all.jsonl", limit=limit)
    _print_records(records)


@logs_app.command("errors")
def logs_errors(
    run: Optional[str] = typer.Option(None, "--run", help="Run ID (default: latest)"),
    path: Optional[str] = typer.Option(None, "--path", "-p", help="Repo path"),
) -> None:
    """Show ERROR and CRITICAL records for a run."""
    log_dir = _log_dir(path)
    run_dir = _resolve_run_dir(log_dir, run)
    if run_dir is None:
        console.print("[red]No log session found.[/]")
        raise typer.Exit(1)

    console.print(f"[dim]Session:[/] [cyan]{run_dir.name}[/] — errors only")
    records = _read_jsonl(run_dir / "errors.jsonl")
    if not records:
        console.print("[green]No errors in this session.[/]")
    else:
        _print_records(records)


@logs_app.command("subsystem")
def logs_subsystem(
    name: str = typer.Argument(..., help="Subsystem name (pipeline, parsers, graph_store, …)"),
    run: Optional[str] = typer.Option(None, "--run", help="Run ID (default: latest)"),
    path: Optional[str] = typer.Option(None, "--path", "-p", help="Repo path"),
    limit: int = typer.Option(200, "--limit", "-n", help="Max records to show"),
) -> None:
    """Show log records for a specific subsystem."""
    log_dir = _log_dir(path)
    run_dir = _resolve_run_dir(log_dir, run)
    if run_dir is None:
        console.print("[red]No log session found.[/]")
        raise typer.Exit(1)

    subsystem_file = run_dir / f"{name}.jsonl"
    if not subsystem_file.exists():
        console.print(f"[yellow]No log file found for subsystem '{name}'.[/] Available files:")
        for f in sorted(run_dir.glob("*.jsonl")):
            console.print(f"  {f.stem}")
        raise typer.Exit(1)

    console.print(f"[dim]Session:[/] [cyan]{run_dir.name}[/] — subsystem: [cyan]{name}[/]")
    records = _read_jsonl(subsystem_file, limit=limit)
    _print_records(records)


@logs_app.command("filter")
def logs_filter(
    level: Optional[str] = typer.Option(None, "--level", help="Minimum log level (DEBUG/INFO/WARNING/ERROR)"),
    phase: Optional[str] = typer.Option(None, "--phase", help="Filter by phase name"),
    subsystem: Optional[str] = typer.Option(None, "--subsystem", help="Filter by subsystem"),
    degraded: bool = typer.Option(False, "--degraded", help="Show only degraded records"),
    run: Optional[str] = typer.Option(None, "--run", help="Run ID (default: latest)"),
    path: Optional[str] = typer.Option(None, "--path", "-p", help="Repo path"),
    limit: int = typer.Option(200, "--limit", "-n", help="Max records to show"),
) -> None:
    """Filter log records by level, phase, subsystem, or degraded flag."""
    _LEVEL_NUMS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
    min_level_no = _LEVEL_NUMS.get(level.upper(), 0) if level else 0

    log_dir = _log_dir(path)
    run_dir = _resolve_run_dir(log_dir, run)
    if run_dir is None:
        console.print("[red]No log session found.[/]")
        raise typer.Exit(1)

    records = _read_jsonl(run_dir / "all.jsonl")

    def _matches(r: dict) -> bool:
        if min_level_no and r.get("level_no", 0) < min_level_no:
            return False
        if phase and r.get("phase") != phase:
            return False
        if subsystem and r.get("subsystem") != subsystem:
            return False
        if degraded and not r.get("degraded"):
            return False
        return True

    filtered = [r for r in records if _matches(r)]
    console.print(f"[dim]Session:[/] [cyan]{run_dir.name}[/] — [dim]{len(filtered)} matching records[/]")
    _print_records(filtered, max_rows=limit)


@logs_app.command("tail")
def logs_tail(
    subsystem: Optional[str] = typer.Option(None, "--subsystem", "-s", help="Subsystem to tail"),
    path: Optional[str] = typer.Option(None, "--path", "-p", help="Repo path"),
    interval: float = typer.Option(0.5, "--interval", help="Poll interval in seconds"),
) -> None:
    """Tail the latest log file in real time (polls on file changes)."""
    log_dir = _log_dir(path)
    run_dir = _resolve_run_dir(log_dir, None)
    if run_dir is None:
        console.print("[red]No active log session found.[/] Start a sync to generate logs.")
        raise typer.Exit(1)

    filename = f"{subsystem}.jsonl" if subsystem else "all.jsonl"
    log_file = run_dir / filename
    console.print(f"[dim]Tailing[/] {log_file} [dim](Ctrl+C to stop)[/]")

    seen = 0
    try:
        while True:
            if log_file.exists():
                lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
                new_lines = lines[seen:]
                seen = len(lines)
                for line in new_lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                        ts = (r.get("ts") or "")
                        ts_short = ts[11:19] if len(ts) >= 19 else ts
                        level = r.get("level", "")
                        color = _level_color(level)
                        msg = r.get("msg", "")
                        sub = r.get("subsystem") or ""
                        console.print(
                            f"[dim]{ts_short}[/] [{color}]{level[:4]}[/{color}] "
                            f"[cyan]{sub}[/cyan] {msg}"
                        )
                    except json.JSONDecodeError:
                        console.print(line)
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/]")
