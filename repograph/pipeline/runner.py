"""Pipeline runner — orchestrates the core graph-build phases and fires plugin hooks.

Architecture
------------
The runner has two responsibilities:

1. **Layer A — Core graph build:** direct phase module calls (`p01`–`p12`, and
   optionally `p13` embeddings when enabled) that construct and fill the graph
   store. These steps are ordered in `run_full_pipeline` / `run_incremental_pipeline`.

2. **Layer B — Plugin hooks:** after Layer A (and after optional `p13` in full
   sync), `_fire_hooks` runs the hook sequence:

   - `on_graph_built` — static analyzers (pathways, dead_code, event_topology, …)
   - `on_evidence` — evidence producers
   - `on_export` — exporters (doc_warnings, modules, config_registry, …)

   If `.repograph/runtime/` contains trace files, `on_traces_collected` runs
   dynamic analyzers, then `on_traces_analyzed`.

   Sync-time analysis and artefact generation live in `repograph.plugins.*`;
   there are no separate `pipeline/phases/p11`–`p20` runner steps.

   Failed plugin hooks are logged with ``repograph.utils.logging.warn`` per
   attempt (not ``warn_once``) so repeated syncs still surface errors. Exporters
   use ``warn_once`` for non-fatal best-effort failures — see ``docs/SURFACES.md``.

**Incremental sync:** when the file diff is empty, the runner returns early
(“Already up to date”) **without** calling `_fire_hooks`.

Adding a new analysis feature
------------------------------
Add `repograph/plugins/<kind>/<feature>/plugin.py`, declare hooks on the manifest,
register in `plugins/<kind>/_registry.py` (or discovery when implemented).
"""
from __future__ import annotations

import os
import subprocess
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from repograph.config import (
    DEFAULT_CONTEXT_TOKENS as _DEFAULT_CONTEXT_TOKENS,
    DEFAULT_MIN_COMMUNITY_SIZE as _DEFAULT_MIN_COMMUNITY_SIZE,
    DEFAULT_MODULE_EXPANSION_THRESHOLD as _DEFAULT_MODULE_EXPANSION_THRESHOLD,
)
from repograph.core.models import FileRecord, ParsedFile
from repograph.graph_store.store import GraphStore
from repograph.observability import (
    ObservabilityConfig,
    get_logger,
    init_observability,
    new_run_id,
    set_obs_context,
    shutdown_observability,
    span,
)
from repograph.parsing.symbol_table import SymbolTable
from repograph.utils import logging as rg_log

_logger = get_logger(__name__, subsystem="pipeline")

console = Console()


def _runtime_dir_has_traces(repograph_dir: str) -> bool:
    """True if ``.repograph/runtime`` exists and has at least one entry."""
    td = Path(repograph_dir) / "runtime"
    if not td.is_dir():
        return False
    try:
        return any(td.iterdir())
    except OSError:
        return False


# ---------------------------------------------------------------------------
# RunConfig
# ---------------------------------------------------------------------------

@dataclass
class RunConfig:
    repo_root: str
    repograph_dir: str
    include_git: bool = True
    include_embeddings: bool = False
    full: bool = False
    max_context_tokens: int = _DEFAULT_CONTEXT_TOKENS
    duplicates_same_language_only: bool = True
    strict: bool = False
    continue_on_error: bool = True
    min_community_size: int = _DEFAULT_MIN_COMMUNITY_SIZE
    module_expansion_threshold: int = _DEFAULT_MODULE_EXPANSION_THRESHOLD
    include_tests_config_registry: bool = False
    experimental_phase_plugins: bool = False

    def __post_init__(self) -> None:
        errors: list[str] = []
        if self.min_community_size < 0:
            errors.append(f"min_community_size must be >= 0, got {self.min_community_size}")
        if self.module_expansion_threshold < 1:
            errors.append(
                f"module_expansion_threshold must be >= 1, got {self.module_expansion_threshold}"
            )
        if self.max_context_tokens < 100:
            errors.append(f"max_context_tokens must be >= 100, got {self.max_context_tokens}")
        if not Path(self.repo_root).is_dir():
            errors.append(f"repo_root does not exist or is not a directory: {self.repo_root!r}")
        if errors:
            raise ValueError("Invalid RunConfig:\n" + "\n".join(f"  - {e}" for e in errors))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_experimental_pipeline_phases(
    config: RunConfig,
    store: GraphStore,
    parsed: list[ParsedFile],
) -> None:
    """Run optional phases after graph build, before plugin hooks (SPI extension point)."""
    if not config.experimental_phase_plugins:
        return
    from repograph.plugins.pipeline_phases.registry import iter_pipeline_phases

    for phase in iter_pipeline_phases():
        try:
            phase.run(
                store=store,
                parsed=parsed,
                repo_root=config.repo_root,
                repograph_dir=config.repograph_dir,
                config=config,
            )
        except Exception as exc:
            _handle_optional_phase_failure(
                config, f"experimental pipeline phase {phase.phase_id}", exc,
            )


def _handle_optional_phase_failure(config: RunConfig, phase: str, exc: BaseException) -> None:
    if config.strict:
        raise exc
    if not config.continue_on_error:
        raise RuntimeError(
            f"{phase} failed; pass --continue-on-error to tolerate optional errors: {exc}"
        ) from exc
    console.print(f"[yellow]Warning: {phase} failed: {exc}[/]")


def _fire_hooks(config: RunConfig, store: GraphStore, parsed: list[ParsedFile]) -> dict[str, object]:
    """Fire all post-graph-build plugin hooks in order.

    on_graph_built   — static analyzers run (includes dead_code, event_topology, etc.)
    on_evidence      — evidence producers collect declared/observed data
    on_export        — exporters write meta/ artefacts (doc_warnings, modules, …)
    on_traces_collected — dynamic analyzers overlay runtime traces (when present)
    """
    from repograph.plugins.lifecycle import get_hook_scheduler

    hooks = get_hook_scheduler()
    summary: dict[str, Any] = {"failed_count": 0, "warnings_count": 0, "failed": []}

    def _mark_failed(hook_name: str, plugin_id: str, error: str) -> None:
        summary["failed_count"] = int(summary.get("failed_count", 0)) + 1
        summary["warnings_count"] = int(summary.get("warnings_count", 0)) + 1
        failed = list(summary.get("failed") or [])
        failed.append({"hook": hook_name, "plugin_id": plugin_id, "error": error[:500]})
        summary["failed"] = failed

    # ── on_graph_built ───────────────────────────────────────────────────
    try:
        results = hooks.fire(
            "on_graph_built",
            store=store,
            repo_path=config.repo_root,
            repograph_dir=config.repograph_dir,
            parsed=parsed,
            config=config,
        )
        for r in results:
            if not r.succeeded:
                rg_log.warn(f"on_graph_built: {r.plugin_id} failed: {r.error}")
                _mark_failed("on_graph_built", r.plugin_id, r.error or "")
    except Exception as exc:
        _mark_failed("on_graph_built", "scheduler", f"{type(exc).__name__}: {exc}")
        _handle_optional_phase_failure(config, "on_graph_built hook", exc)

    # ── on_evidence ──────────────────────────────────────────────────────
    try:
        results = hooks.fire(
            "on_evidence",
            store=store,
            repo_path=config.repo_root,
            repograph_dir=config.repograph_dir,
        )
        for r in results:
            if not r.succeeded:
                rg_log.warn(f"on_evidence: {r.plugin_id} failed: {r.error}")
                _mark_failed("on_evidence", r.plugin_id, r.error or "")
    except Exception as exc:
        _mark_failed("on_evidence", "scheduler", f"{type(exc).__name__}: {exc}")
        _handle_optional_phase_failure(config, "on_evidence hook", exc)

    # ── on_export ────────────────────────────────────────────────────────
    try:
        results = hooks.fire(
            "on_export",
            store=store,
            repograph_dir=config.repograph_dir,
            config=config,
        )
        for r in results:
            if not r.succeeded:
                rg_log.warn(f"on_export: {r.plugin_id} failed: {r.error}")
                _mark_failed("on_export", r.plugin_id, r.error or "")
    except Exception as exc:
        _mark_failed("on_export", "scheduler", f"{type(exc).__name__}: {exc}")
        _handle_optional_phase_failure(config, "on_export hook", exc)

    # ── on_traces_collected (dynamic analysis) ───────────────────────────
    trace_dir = Path(config.repograph_dir) / "runtime"
    if trace_dir.exists() and any(trace_dir.iterdir()):
        rg_log.info(f"Dynamic traces found — running overlay analysis")
        try:
            results = hooks.fire(
                "on_traces_collected",
                trace_dir=trace_dir,
                store=store,
                repo_path=config.repo_root,
                repo_root=config.repo_root,
                config=config,
            )
            for r in results:
                if not r.succeeded:
                    rg_log.warn(f"on_traces_collected: {r.plugin_id} failed: {r.error}")
                    _mark_failed("on_traces_collected", r.plugin_id, r.error or "")
            hooks.fire("on_traces_analyzed", store=store, config=config)
            n_findings = sum(len(r.result or []) for r in results if r.succeeded)
            # Findings = alert-style rows only (e.g. static-dead ∩ observed, new dynamic
            # edges). Persisted runtime_* columns are logged by the overlay plugin.
            rg_log.success(
                f"Dynamic overlay: {n_findings} alert finding(s) "
                f"(0 is normal if dead-code already skipped observed symbols)"
            )
        except Exception as exc:
            _mark_failed("on_traces_collected", "scheduler", f"{type(exc).__name__}: {exc}")
            _handle_optional_phase_failure(config, "dynamic analysis hooks", exc)
    return summary


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def run_full_pipeline(config: RunConfig) -> dict:
    """Run the full graph-build pipeline against a repository.

    Phases p01–p13 build the graph from scratch.  All analysis and export work
    is performed by plugin hooks fired at the end — no direct p15–p20 calls.
    """
    from repograph.pipeline.phases import (
        p01_walk, p02_structure, p03_parse, p04_imports,
        p05_calls, p05b_callbacks, p06_heritage, p07_variables, p08_types,
        p09_communities, p10_processes, p12_coupling,
    )
    from repograph.pipeline.phases import p03b_framework_tags, p05c_http_calls
    from repograph.docs.staleness import StalenessTracker
    from repograph.pipeline.incremental import IncrementalDiff
    from repograph.pipeline.sync_state import clear_sync_lock, write_sync_lock
    from repograph.pipeline.health import (
        build_health_failure_report, build_health_report, write_health_json,
    )

    _run_id = new_run_id()
    init_observability(ObservabilityConfig(
        log_dir=Path(config.repograph_dir) / "logs",
        run_id=_run_id,
    ))
    set_obs_context(phase="full_sync")
    _logger.info("full pipeline started", repo_root=config.repo_root, run_id=_run_id)

    write_sync_lock(config.repograph_dir, mode="full",
                    repo_root=config.repo_root, phase="starting")
    store: GraphStore | None = None
    files: list[FileRecord] = []
    parsed: list[ParsedFile] = []

    try:
        db_path = os.path.join(config.repograph_dir, "graph.db")
        from repograph.graph_store.store import _delete_db_dir
        _delete_db_dir(db_path)
        store = GraphStore(db_path)
        store.initialize_schema()

        symbol_table = SymbolTable()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:

            # ── CORE GRAPH BUILD (p01–p12) ────────────────────────────────
            task = progress.add_task("Phase 1: Walking repository...", total=None)
            files = p01_walk.run(config.repo_root)
            progress.update(task, description=f"Phase 1: Found {len(files)} files")

            progress.add_task("Phase 2: Building folder structure...", total=None)
            p02_structure.run(files, store, config.repo_root)

            task3 = progress.add_task(f"Phase 3: Parsing {len(files)} files...", total=None)
            parsed = p03_parse.run(files, store, symbol_table)
            progress.update(task3, description=f"Phase 3: Parsed {len(parsed)} files")

            progress.add_task("Phase 3b: Applying framework tags...", total=None)
            p03b_framework_tags.run(parsed, store)

            progress.add_task("Phase 4: Resolving imports...", total=None)
            p04_imports.run(parsed, store, symbol_table, config.repo_root)

            progress.add_task("Phase 5: Resolving calls...", total=None)
            p05_calls.run(parsed, store, symbol_table)

            progress.add_task("Phase 5b: Detecting callback registrations...", total=None)
            p05b_callbacks.run(parsed, store, symbol_table)

            progress.add_task("Phase 5c: Detecting HTTP call edges...", total=None)
            p05c_http_calls.run(parsed, store)

            progress.add_task("Phase 6: Resolving inheritance...", total=None)
            p06_heritage.run(parsed, store, symbol_table)

            progress.add_task("Phase 7: Tracking variables...", total=None)
            p07_variables.run(parsed, store)

            progress.add_task("Phase 8: Analysing type annotations...", total=None)
            p08_types.run(parsed, store, symbol_table)

            progress.add_task("Phase 9: Detecting communities...", total=None)
            p09_communities.run(store, min_community_size=config.min_community_size)

            progress.add_task("Phase 10: Scoring entry points...", total=None)
            p10_processes.run(store)

            if config.include_git:
                progress.add_task("Phase 12: Analyzing git coupling...", total=None)
                p12_coupling.run(store, config.repo_root)

            if config.include_embeddings:
                progress.add_task("Phase 13: Building embeddings...", total=None)
                try:
                    from repograph.pipeline.phases import p13_embeddings
                    p13_embeddings.run(store)
                except ImportError:
                    if config.strict:
                        raise
                    console.print("[yellow]sentence-transformers not installed, skipping embeddings[/]")

            # ── PLUGIN HOOKS ──────────────────────────────────────────────
            # on_graph_built → on_evidence → on_export → on_traces_collected
            # No direct phase calls below this line.
            progress.add_task("Running plugin hooks...", total=None)

        _run_experimental_pipeline_phases(config, store, parsed)
        hook_summary = _fire_hooks(config, store, parsed)

        staleness = StalenessTracker(config.repograph_dir)
        differ = IncrementalDiff(config.repograph_dir)
        differ.save_index({fr.path: fr for fr in files})

        stats = store.get_stats()
        write_health_json(
            config.repograph_dir,
            build_health_report(
                store, stats,
                repo_root=config.repo_root, repograph_dir=config.repograph_dir,
                sync_mode="full", files_walked=len(files), strict=config.strict,
                hook_summary=hook_summary,
            ),
        )
        return stats

    except BaseException as exc:
        partial = None
        if store is not None:
            try:
                partial = store.get_stats()
            except Exception as stats_exc:
                _logger.warning("store.get_stats() failed during error recovery", exc_msg=str(stats_exc))
        try:
            write_health_json(
                config.repograph_dir,
                build_health_failure_report(
                    repo_root=config.repo_root, repograph_dir=config.repograph_dir,
                    sync_mode="full", error_phase="pipeline",
                    error_message=f"{type(exc).__name__}: {exc}", strict=config.strict,
                    partial_stats=partial,
                ),
            )
        except Exception as health_exc:
            _logger.warning("write_health_json failed during error recovery", exc_msg=str(health_exc))
        _logger.error("full pipeline failed", exc_type=type(exc).__name__, exc_msg=str(exc))
        console.print(f"[red bold]Sync failed:[/] {exc}")
        raise
    finally:
        clear_sync_lock(config.repograph_dir)
        if store is not None:
            try:
                store.close()
            except Exception as close_exc:
                _logger.warning("store.close() failed during cleanup", exc_msg=str(close_exc))
        shutdown_observability()


# ---------------------------------------------------------------------------
# Incremental pipeline
# ---------------------------------------------------------------------------

def run_incremental_pipeline(config: RunConfig) -> dict:
    """Run incremental sync — re-processes changed/added files and affected callers/importers.

    Affected paths are expanded via :func:`expand_reparse_paths_for_incremental` so
    ``CALLS`` edges are rebuilt after callee files are replaced or removed.

    Same hook sequence as the full pipeline fires at the end.
    """
    from repograph.docs.staleness import StalenessTracker
    from repograph.pipeline.incremental import IncrementalDiff, expand_reparse_paths_for_incremental
    from repograph.pipeline.phases import (
        p01_walk, p03_parse, p04_imports,
        p05_calls, p05b_callbacks, p06_heritage, p07_variables, p08_types,
        p09_communities, p10_processes,
    )
    from repograph.pipeline.phases import p03b_framework_tags, p05c_http_calls
    from repograph.pipeline.sync_state import clear_sync_lock, write_sync_lock
    from repograph.pipeline.health import (
        build_health_failure_report, build_health_report, write_health_json,
    )

    _run_id = new_run_id()
    init_observability(ObservabilityConfig(
        log_dir=Path(config.repograph_dir) / "logs",
        run_id=_run_id,
    ))
    set_obs_context(phase="incremental_sync")
    _logger.info("incremental pipeline started", repo_root=config.repo_root, run_id=_run_id)

    write_sync_lock(config.repograph_dir, mode="incremental",
                    repo_root=config.repo_root, phase="starting")
    store: GraphStore | None = None
    parsed: list[ParsedFile] = []

    try:
        db_path = os.path.join(config.repograph_dir, "graph.db")
        store = GraphStore(db_path)
        store.initialize_schema()

        staleness = StalenessTracker(config.repograph_dir)
        differ = IncrementalDiff(config.repograph_dir)

        current_files = p01_walk.run(config.repo_root)
        current_map = {fr.path: fr for fr in current_files}
        diff = differ.compute(current_map)

        if not diff.added and not diff.removed and not diff.changed:
            # Even with no source diff, new JSONL under .repograph/runtime/ must merge
            # via hooks (on_traces_collected). Otherwise ``repograph sync`` after pytest
            # would no-op and skip the dynamic overlay.
            if _runtime_dir_has_traces(config.repograph_dir):
                console.print(
                    "[cyan]No source file changes; refreshing derived index data and "
                    "merging runtime traces...[/]"
                )
                parsed = []
                store.clear_communities()
                store.clear_pathways()
                store.clear_processes()
                p09_communities.run(store, min_community_size=config.min_community_size)
                p10_processes.run(store)
                _run_experimental_pipeline_phases(config, store, parsed)
                hook_summary = _fire_hooks(config, store, parsed)
                differ.save_index(current_map)
                staleness.save()
                stats = store.get_stats()
                write_health_json(
                    config.repograph_dir,
                    build_health_report(
                        store, stats,
                        repo_root=config.repo_root, repograph_dir=config.repograph_dir,
                        sync_mode="incremental_traces_only", files_walked=len(current_files),
                        strict=config.strict,
                        hook_summary=hook_summary,
                    ),
                )
                return stats
            console.print("[green]Already up to date.[/]")
            stats = store.get_stats()
            write_health_json(
                config.repograph_dir,
                build_health_report(
                    store, stats,
                    repo_root=config.repo_root, repograph_dir=config.repograph_dir,
                    sync_mode="incremental_unchanged", files_walked=len(current_files),
                    strict=config.strict,
                ),
            )
            return stats

        console.print(
            f"[cyan]Incremental: +{len(diff.added)} added, "
            f"~{len(diff.changed)} changed, -{len(diff.removed)} removed[/]"
        )

        current_path_set = set(current_map.keys())
        reparse_paths = expand_reparse_paths_for_incremental(
            store,
            added=diff.added,
            changed=diff.changed,
            removed=diff.removed,
            current_paths=current_path_set,
        )
        extra = len(reparse_paths - (diff.added | diff.changed))
        if extra:
            console.print(
                f"  [dim]also re-parsing {extra} caller/importer file(s) to restore CALLS[/]"
            )

        for path in diff.removed:
            store.delete_file_nodes(path)
            console.print(f"  [red]removed[/] {path}")

        for path in diff.changed:
            store.delete_file_nodes(path)
            staleness.mark_stale_for_file(path)
            console.print(f"  [yellow]changed[/] {path}")

        reparse_files = [fr for fr in current_files if fr.path in reparse_paths]

        if reparse_files:
            symbol_table = SymbolTable()
            for fn_dict in store.get_all_functions_for_symbol_table():
                if fn_dict["file_path"] not in reparse_paths:
                    symbol_table.add_function_from_dict(fn_dict)
            for cls_dict in store.get_all_classes_for_symbol_table():
                if cls_dict["file_path"] not in reparse_paths:
                    symbol_table.add_class_from_dict(cls_dict)

            parsed = p03_parse.run(reparse_files, store, symbol_table)
            p03b_framework_tags.run(parsed, store)
            p04_imports.run(parsed, store, symbol_table, config.repo_root)
            p05_calls.run(parsed, store, symbol_table)
            p05b_callbacks.run(parsed, store, symbol_table)
            p05c_http_calls.run(parsed, store)
            p06_heritage.run(parsed, store, symbol_table)
            p07_variables.run(parsed, store, reparse_paths=reparse_paths)
            p08_types.run(parsed, store, symbol_table)

        store.clear_communities()
        store.clear_pathways()
        store.clear_processes()

        p09_communities.run(store, min_community_size=config.min_community_size)
        p10_processes.run(store)

        # ── PLUGIN HOOKS (same sequence as full pipeline) ─────────────────
        _run_experimental_pipeline_phases(config, store, parsed)
        hook_summary = _fire_hooks(config, store, parsed)

        differ.save_index(current_map)
        staleness.save()

        stats = store.get_stats()
        write_health_json(
            config.repograph_dir,
            build_health_report(
                store, stats,
                repo_root=config.repo_root, repograph_dir=config.repograph_dir,
                sync_mode="incremental", files_walked=len(current_files), strict=config.strict,
                hook_summary=hook_summary,
            ),
        )
        return stats

    except BaseException as exc:
        partial = None
        if store is not None:
            try:
                partial = store.get_stats()
            except Exception as stats_exc:
                _logger.warning("store.get_stats() failed during error recovery", exc_msg=str(stats_exc))
        try:
            write_health_json(
                config.repograph_dir,
                build_health_failure_report(
                    repo_root=config.repo_root, repograph_dir=config.repograph_dir,
                    sync_mode="incremental", error_phase="pipeline",
                    error_message=f"{type(exc).__name__}: {exc}", strict=config.strict,
                    partial_stats=partial,
                ),
            )
        except Exception as health_exc:
            _logger.warning("write_health_json failed during error recovery", exc_msg=str(health_exc))
        _logger.error("incremental pipeline failed", exc_type=type(exc).__name__, exc_msg=str(exc))
        console.print(f"[red bold]Incremental sync failed:[/] {exc}")
        raise
    finally:
        clear_sync_lock(config.repograph_dir)
        if store is not None:
            try:
                store.close()
            except Exception as close_exc:
                _logger.warning("store.close() failed during cleanup", exc_msg=str(close_exc))
        shutdown_observability()


def run_full_sync_with_tests(
    config: RunConfig,
    *,
    pytest_targets: list[str] | None = None,
) -> dict:
    """Full pipeline, trace install, pytest, trace collect, then incremental sync.

    Used by ``repograph sync --full-with-tests``. Merges JSONL runtime traces into
    the graph via :func:`run_incremental_pipeline` (including the trace-only
    path when no source files changed).
    """
    root = config.repo_root
    py = sys.executable
    targets = pytest_targets if pytest_targets is not None else ["tests"]

    console.print("[cyan]Step 1/4: full pipeline...[/]")
    run_full_pipeline(config)

    console.print("[cyan]Step 2/4: repograph trace install (pytest mode)...[/]")
    r = subprocess.run(
        [py, "-m", "repograph", "trace", "install", root],
        cwd=root,
    )
    if r.returncode != 0:
        console.print("[yellow]trace install failed; pytest may not emit JSONL traces.[/]")

    console.print(f"[cyan]Step 3/4: pytest {' '.join(targets)}...[/]")
    r = subprocess.run([py, "-m", "pytest", *targets], cwd=root)
    if r.returncode != 0:
        msg = f"pytest exited with code {r.returncode}"
        if config.strict:
            raise RuntimeError(msg)
        console.print(
            f"[yellow]{msg} — continuing to merge traces "
            "(use [bold]--strict[/] on sync to abort on pytest failure)[/]"
        )

    console.print("[cyan]Step 3b: trace collect (summary)...[/]")
    subprocess.run([py, "-m", "repograph", "trace", "collect", root], cwd=root)

    console.print("[cyan]Step 4/4: incremental sync (merge runtime traces)...[/]")
    return run_incremental_pipeline(config)
