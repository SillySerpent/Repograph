"""Typer app definitions, sub-typers, and shared CLI helpers.

This module defines the root ``app`` and all registered sub-typers.  It NEVER
imports from ``repograph.surfaces.cli.commands`` — that import direction lives
exclusively in ``repograph.surfaces.cli.__init__``.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import typer
from rich.console import Console

from repograph.observability import (
    ensure_observability_session,
    get_logger,
    new_run_id,
    set_obs_context,
    shutdown_observability,
)

_logger = get_logger(__name__, subsystem="cli")

# ---------------------------------------------------------------------------
# App / sub-typer definitions
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="repograph",
    help="AI-oriented repository intelligence layer.",
    no_args_is_help=True,
)

pathway_app = typer.Typer(help="Pathway commands.")
app.add_typer(pathway_app, name="pathway")

trace_app = typer.Typer(
    name="trace",
    help=(
        "Dynamic analysis helpers for advanced/manual workflows.\n\n"
        "Routine runtime overlay now happens automatically on [bold]repograph sync --full[/].\n"
        "Use trace subcommands only when you want explicit control over instrumentation\n"
        "or to inspect raw trace payloads under .repograph/runtime/."
    ),
)
app.add_typer(trace_app, name="trace")

from repograph.interactive.logs_handler import logs_app  # noqa: E402
app.add_typer(logs_app, name="logs")

console = Console()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _print_not_indexed_error() -> None:
    console.print("[red]Error:[/] No RepoGraph index found. Run [bold]repograph sync[/] first.")


@contextmanager
def _cli_command_session(repo_hint: str | None, *, command: str):
    """Create a short-lived structured-log session for direct CLI commands."""
    from repograph.settings import get_repo_root, repograph_dir
    from repograph.exceptions import RepographNotFoundError

    try:
        root = get_repo_root(repo_hint)
    except RepographNotFoundError:
        root = os.path.abspath(repo_hint or os.getcwd())

    started_run = ensure_observability_session(Path(repograph_dir(root)) / "logs")
    _logger.info("cli command started", command=command, repo_root=root)
    try:
        yield root
        _logger.info("cli command finished", command=command, repo_root=root)
    except Exception as exc:
        _logger.error(
            "cli command failed",
            command=command,
            repo_root=root,
            exc_type=type(exc).__name__,
            exc_msg=str(exc),
        )
        raise
    finally:
        if started_run is not None:
            shutdown_observability()


def _version_callback(value: bool) -> None:
    if value:
        import importlib.metadata
        try:
            version = importlib.metadata.version("repograph")
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
        typer.echo(f"repograph {version}")
        raise typer.Exit()


@app.callback()
def _cli_startup(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Set a stable command_id on the observability context for every CLI invocation."""
    command_id = new_run_id()
    set_obs_context(command_id=command_id)
    _logger.debug("CLI invoked", command=ctx.invoked_subcommand, command_id=command_id)


def _get_root_and_store(repo_path: str | None = None):
    """Return (repo_root, store) for the current repo."""
    import click

    from repograph.settings import get_repo_root, db_path, is_initialized, repograph_dir
    from repograph.exceptions import RepographNotFoundError
    from repograph.graph_store.store import GraphStore

    try:
        root = get_repo_root(repo_path)
    except RepographNotFoundError:
        _print_not_indexed_error()
        raise typer.Exit(1)
    if not is_initialized(root):
        _print_not_indexed_error()
        raise typer.Exit(1)

    started_run = ensure_observability_session(Path(repograph_dir(root)) / "logs")
    if started_run is not None:
        ctx = click.get_current_context(silent=True)
        if ctx is not None:
            ctx.call_on_close(shutdown_observability)

    store = GraphStore(db_path(root))
    store.prepare_read_state()
    return root, store


def _get_service(path: str | None = None):
    """Return (repo_root, RepoGraph API wrapper) for initialized repos."""
    from repograph.surfaces.api import RepoGraph
    from repograph.settings import get_repo_root, repograph_dir, is_initialized
    from repograph.exceptions import RepographNotFoundError

    try:
        root = get_repo_root(path)
    except RepographNotFoundError:
        _print_not_indexed_error()
        raise typer.Exit(1)
    if not is_initialized(root):
        _print_not_indexed_error()
        raise typer.Exit(1)
    return root, RepoGraph(root, repograph_dir=repograph_dir(root))
