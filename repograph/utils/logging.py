"""User-facing log lines for the RepoGraph CLI and selected plugins.

This module prints to **stderr** via Rich; it is **not** Python's stdlib
:class:`logging` stack (no logger hierarchy, no handler configuration).

**Functions**

- ``info``, ``warn``, ``error``, ``debug``, ``success`` — print every time.
- ``warn_once(msg)`` — prints at most once per process for an **identical**
  message string (used by exporters and pathway tooling to avoid flooding the
  console when optional steps fail repeatedly).

**Where it is used**

- Pipeline hook failures: ``repograph/pipeline/runner.py`` uses ``warn`` (not
  ``warn_once``) per failed plugin execution so repeated syncs still show errors.
- Best-effort plugin/exporter paths: ``warn_once`` for non-fatal read/generate
  failures.

For how CLI, API, and MCP relate, see ``docs/SURFACES.md``.
"""
from __future__ import annotations

from rich.console import Console

_console = Console(stderr=True)
_warned_once: set[str] = set()


def info(msg: str) -> None:
    _console.print(f"[cyan]info[/]  {msg}")


def warn(msg: str) -> None:
    _console.print(f"[yellow]warn[/]  {msg}")


def error(msg: str) -> None:
    _console.print(f"[red]error[/] {msg}")


def debug(msg: str) -> None:
    _console.print(f"[dim]debug {msg}[/]")


def success(msg: str) -> None:
    _console.print(f"[green]✓[/] {msg}")


def warn_once(msg: str) -> None:
    if msg in _warned_once:
        return
    _warned_once.add(msg)
    warn(msg)
