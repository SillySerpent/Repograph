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
import shutil
import sys
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from typing import Any

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from repograph.config import (
    DEFAULT_CONTEXT_TOKENS as _DEFAULT_CONTEXT_TOKENS,
    DEFAULT_MIN_COMMUNITY_SIZE as _DEFAULT_MIN_COMMUNITY_SIZE,
    DEFAULT_MODULE_EXPANSION_THRESHOLD as _DEFAULT_MODULE_EXPANSION_THRESHOLD,
)
from repograph.core.models import FileRecord, ParsedFile
from repograph.core.plugin_framework.contracts import HookName
from repograph.graph_store.store import GraphStore
from repograph.observability import (
    ObservabilityConfig,
    get_logger,
    init_observability,
    make_thread_context,
    new_run_id,
    set_obs_context,
    shutdown_observability,
    span,
)
from repograph.observability._context import get_context_var
from repograph.parsing.symbol_table import SymbolTable
from repograph.utils import logging as rg_log

_logger = get_logger(__name__, subsystem="pipeline")

console = Console()


@contextmanager
def _phase_scope(phase: str, **metadata: Any):
    """Set phase context and emit a span for one meaningful runner stage."""
    prev_phase = get_context_var("phase")
    set_obs_context(phase=phase)
    try:
        with span(phase, subsystem="pipeline", **metadata) as span_ctx:
            yield span_ctx
    finally:
        set_obs_context(phase=prev_phase or "")


def _validate_run_config_paths(config: "RunConfig") -> None:
    """Fail fast if runner is called with invalid path-like config values."""
    if not isinstance(config.repo_root, str):
        raise ValueError(f"RunConfig.repo_root must be a str path, got {type(config.repo_root).__name__}")
    if not isinstance(config.repograph_dir, str):
        raise ValueError(
            f"RunConfig.repograph_dir must be a str path, got {type(config.repograph_dir).__name__}"
        )
    if not Path(config.repo_root).is_dir():
        raise ValueError(f"RunConfig.repo_root must be an existing directory: {config.repo_root!r}")


def _runtime_dir_has_traces(repograph_dir: str) -> bool:
    """True if ``.repograph/runtime`` exists and has at least one entry."""
    td = Path(repograph_dir) / "runtime"
    if not td.is_dir():
        return False
    try:
        return any(td.iterdir())
    except OSError:
        return False


def _clear_runtime_trace_dir(repograph_dir: str) -> None:
    """Remove any stale runtime trace files before a new dynamic full sync."""
    td = Path(repograph_dir) / "runtime"
    if td.is_dir():
        shutil.rmtree(td)
    td.mkdir(parents=True, exist_ok=True)


def _trace_inventory(repograph_dir: str) -> dict[str, int]:
    """Return a small summary of trace files currently on disk."""
    from repograph.runtime.trace_format import collect_trace_files

    files = collect_trace_files(repograph_dir)
    total_records = 0
    for trace_file in files:
        try:
            with trace_file.open(encoding="utf-8", errors="replace") as fh:
                total_records += sum(1 for _ in fh)
        except OSError:
            continue
    return {
        "trace_file_count": len(files),
        "trace_record_count": total_records,
    }


def _repo_has_pytest_signal(repo_root: str) -> bool:
    """True when ``pyproject.toml`` explicitly configures pytest."""
    pyproject = Path(repo_root) / "pyproject.toml"
    if not pyproject.is_file():
        return False
    try:
        with pyproject.open("rb") as fh:
            data = tomllib.load(fh)
    except Exception:
        return False
    tool = data.get("tool")
    if not isinstance(tool, dict):
        return False
    pytest_cfg = tool.get("pytest")
    if not isinstance(pytest_cfg, dict):
        return False
    return "ini_options" in pytest_cfg


def _resolve_sync_test_command(repo_root: str) -> tuple[list[str] | None, str | None]:
    """Resolve the automatic dynamic-full test command."""
    from repograph.config import load_sync_test_command

    override = load_sync_test_command(repo_root)
    if override:
        return override, "config_override"

    if _repo_has_pytest_signal(repo_root):
        tests_dir = Path(repo_root) / "tests"
        if tests_dir.is_dir():
            return [sys.executable, "-m", "pytest", "tests"], "pyproject_tests_dir"
        return [sys.executable, "-m", "pytest"], "pyproject"
    return None, None


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


def _get_function_ids_in_paths(store: GraphStore, file_paths: set[str]) -> set[str]:
    """Return the set of function IDs whose file_path is in ``file_paths``."""
    if not file_paths:
        return set()
    try:
        rows = store.query(
            "MATCH (f:Function) WHERE f.file_path IN $fps RETURN f.id",
            {"fps": list(file_paths)},
        )
        return {r[0] for r in rows}
    except Exception:
        return set()


def _run_phases_parallel(
    config: RunConfig,
    parsed: list[ParsedFile],
    store: GraphStore,
    symbol_table: SymbolTable,
    *,
    include_git: bool = False,
    reparse_paths: set[str] | None = None,
) -> None:
    """Run dependency-ordered mid-pipeline phases with parallel waves.

    p05 call resolution depends on p04 import resolution (resolved_path and
    cross-lang import edges). To preserve correctness, p04 must complete first.
    Remaining phases then run in parallel because they read immutable p03 data
    and write disjoint relationship families.

    Failures in individual phases are handled according to ``config.strict`` and
    ``config.continue_on_error``; they never silently discard work.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from repograph.pipeline.phases import (
        p04_imports, p05_calls, p05b_callbacks, p05c_http_calls,
        p06_heritage, p06b_layer_classify, p07_variables, p08_types,
    )

    # Dependency barrier: p04 must finish before p05 for best correctness.
    # In continue-on-error mode we still run the remaining phases so callers can
    # collect partial outputs while seeing the explicit p04 failure warning.
    try:
        with _phase_scope("p04_imports", parsed_files=len(parsed)):
            p04_imports.run(parsed, store, symbol_table, config.repo_root)
    except BaseException as exc:
        _handle_optional_phase_failure(config, "phase p04_imports", exc)

    phase_tasks: dict[str, Callable[[], object]] = {
        "p05_calls":     lambda: p05_calls.run(parsed, store, symbol_table),
        "p05b_callbacks": lambda: p05b_callbacks.run(parsed, store, symbol_table),
        "p05c_http":     lambda: p05c_http_calls.run(parsed, store),
        "p06_heritage":  lambda: p06_heritage.run(parsed, store, symbol_table),
        "p06b_layers":   lambda: p06b_layer_classify.run(parsed, store),
        "p07_variables": lambda: (
            p07_variables.run(parsed, store, reparse_paths=reparse_paths)
            if reparse_paths is not None
            else p07_variables.run(parsed, store)
        ),
        "p08_types":     lambda: p08_types.run(parsed, store, symbol_table),
    }
    if include_git:
        from repograph.pipeline.phases import p12_coupling
        phase_tasks["p12_coupling"] = lambda: p12_coupling.run(store, config.repo_root)

    failures: list[tuple[str, BaseException]] = []

    def _wrap_phase(name: str, fn: Callable[[], object]) -> Callable[[], object]:
        def _run() -> object:
            with _phase_scope(name, parsed_files=len(parsed)):
                return fn()

        return _run

    with ThreadPoolExecutor(max_workers=len(phase_tasks)) as ex:
        future_to_name = {
            ex.submit(make_thread_context().run, _wrap_phase(name, fn)): name
            for name, fn in phase_tasks.items()
        }
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            exc = future.exception()
            if exc:
                failures.append((name, exc))

    for name, exc in failures:
        _handle_optional_phase_failure(config, f"phase {name}", exc)


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
    _logger.warning(
        "optional phase failed",
        phase=phase,
        exc_type=type(exc).__name__,
        exc_msg=str(exc),
        strict=config.strict,
        continue_on_error=config.continue_on_error,
    )
    if config.strict:
        raise exc
    if not config.continue_on_error:
        raise RuntimeError(
            f"{phase} failed; pass --continue-on-error to tolerate optional errors: {exc}"
        ) from exc
    console.print(f"[yellow]Warning: {phase} failed: {exc}[/]")


def _ensure_scheduler_bootstrapped() -> None:
    """Bootstrap plugin scheduler on the main thread before parallel parse."""
    from repograph.plugins.lifecycle import get_hook_scheduler

    get_hook_scheduler()


def _fire_hooks(
    config: RunConfig,
    store: GraphStore,
    parsed: list[ParsedFile],
    *,
    run_graph_built: bool = True,
    run_dynamic: bool = True,
    run_evidence: bool = True,
    run_export: bool = True,
) -> dict[str, object]:
    """Fire all post-graph-build plugin hooks in order.

    on_graph_built      — static analyzers run (dead_code, pathways, duplicates, ...)
    on_traces_collected — dynamic analyzers overlay runtime traces (when present)
    on_evidence         — evidence producers collect declared/observed data
    on_export           — exporters write meta/artefacts (doc_warnings, modules, ...)

    Exporters run after dynamic analysis so generated artefacts reflect the
    final graph state, including runtime-cleared dead-code flags.
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

    def _run_stage(
        hook_name: HookName,
        failure_label: str,
        **kwargs: Any,
    ) -> list[Any]:
        try:
            with span(
                f"hook_stage.{hook_name}",
                subsystem="pipeline",
                hook=hook_name,
            ):
                results = hooks.fire(hook_name, **kwargs)
            for r in results:
                if not r.succeeded:
                    rg_log.warn(f"{hook_name}: {r.plugin_id} failed: {r.error}")
                    _mark_failed(hook_name, r.plugin_id, r.error or "")
            return list(results)
        except Exception as exc:
            _mark_failed(hook_name, "scheduler", f"{type(exc).__name__}: {exc}")
            _handle_optional_phase_failure(config, failure_label, exc)
            return []

    if run_graph_built:
        with _phase_scope("hook_stage.on_graph_built"):
            _run_stage(
                "on_graph_built",
                "on_graph_built hook",
                store=store,
                repo_path=config.repo_root,
                repograph_dir=config.repograph_dir,
                parsed=parsed,
                config=config,
            )

    trace_dir = Path(config.repograph_dir) / "runtime"
    if run_dynamic and trace_dir.exists() and any(trace_dir.iterdir()):
        rg_log.info("Dynamic traces found — running overlay analysis")
        with _phase_scope("hook_stage.on_traces_collected"):
            results = _run_stage(
                "on_traces_collected",
                "dynamic analysis hooks",
                trace_dir=trace_dir,
                store=store,
                repo_path=config.repo_root,
                repo_root=config.repo_root,
                config=config,
            )
        try:
            with _phase_scope("hook_stage.on_traces_analyzed"):
                hooks.fire("on_traces_analyzed", store=store, config=config)
        except Exception as exc:
            _mark_failed("on_traces_analyzed", "scheduler", f"{type(exc).__name__}: {exc}")
            _handle_optional_phase_failure(config, "on_traces_analyzed hook", exc)
        n_findings = sum(len(r.result or []) for r in results if getattr(r, "succeeded", False))
        summary["dynamic_findings_count"] = n_findings
        rg_log.success(
            f"Dynamic overlay: {n_findings} alert finding(s) "
            f"(0 is normal if dead-code already skipped observed symbols)"
        )

    if run_evidence:
        with _phase_scope("hook_stage.on_evidence"):
            _run_stage(
                "on_evidence",
                "on_evidence hook",
                store=store,
                repo_path=config.repo_root,
                repograph_dir=config.repograph_dir,
            )

    if run_export:
        with _phase_scope("hook_stage.on_export"):
            _run_stage(
                "on_export",
                "on_export hook",
                store=store,
                repograph_dir=config.repograph_dir,
                config=config,
            )
    return summary


def _merge_hook_summaries(*parts: dict[str, Any]) -> dict[str, Any]:
    """Merge multiple hook summary payloads into one reportable dict."""
    failed: list[dict[str, Any]] = []
    dynamic_findings_count = 0
    for part in parts:
        failed.extend(list(part.get("failed") or []))
        dynamic_findings_count += int(part.get("dynamic_findings_count") or 0)
    return {
        "failed_count": len(failed),
        "warnings_count": len(failed),
        "failed": failed,
        "dynamic_findings_count": dynamic_findings_count,
    }


def _count_valid_runtime_observations(store: GraphStore) -> int:
    """Count functions whose persisted runtime observations match current source."""
    total = 0
    for fn in store.get_all_functions():
        if fn.get("runtime_observed") and (fn.get("runtime_observed_for_hash") or "") == (
            fn.get("source_hash") or ""
        ):
            total += 1
    return total


def _run_full_build_steps(config: RunConfig, store: GraphStore) -> tuple[list[FileRecord], list[ParsedFile]]:
    """Execute the full static graph-build phases and return ``(files, parsed)``."""
    from repograph.pipeline.phases import (
        p01_walk, p02_structure, p03_parse, p09_communities, p10_processes,
    )
    from repograph.pipeline.phases import p03b_framework_tags

    symbol_table = SymbolTable()
    _ensure_scheduler_bootstrapped()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Phase 1: Walking repository...", total=None)
        with _phase_scope("p01_walk", repo_root=config.repo_root) as phase_span:
            files = p01_walk.run(config.repo_root)
            phase_span.add_metadata(file_count=len(files))
        progress.update(task, description=f"Phase 1: Found {len(files)} files")

        progress.add_task("Phase 2: Building folder structure...", total=None)
        with _phase_scope("p02_structure", file_count=len(files)):
            p02_structure.run(files, store, config.repo_root)

        task3 = progress.add_task(f"Phase 3: Parsing {len(files)} files...", total=None)
        with _phase_scope("p03_parse", file_count=len(files)) as phase_span:
            parsed = p03_parse.run(files, store, symbol_table)
            phase_span.add_metadata(parsed_files=len(parsed))
        progress.update(task3, description=f"Phase 3: Parsed {len(parsed)} files")

        progress.add_task("Phase 3b: Applying framework tags...", total=None)
        with _phase_scope("p03b_framework_tags", parsed_files=len(parsed)):
            p03b_framework_tags.run(parsed, store)

        progress.add_task("Phases 4-8: Resolving relationships (parallel)...", total=None)
        with _phase_scope("p04_to_p08_parallel", parsed_files=len(parsed), include_git=config.include_git):
            _run_phases_parallel(
                config,
                parsed,
                store,
                symbol_table,
                include_git=config.include_git,
            )

        progress.add_task("Phase 9: Detecting communities...", total=None)
        with _phase_scope("p09_communities", min_community_size=config.min_community_size):
            p09_communities.run(store, min_community_size=config.min_community_size)
        p09_communities.save_community_snapshot(config.repograph_dir, store)

        progress.add_task("Phase 10: Scoring entry points...", total=None)
        with _phase_scope("p10_processes"):
            p10_processes.run(store)

        if config.include_embeddings:
            progress.add_task("Phase 13: Building embeddings...", total=None)
            try:
                from repograph.pipeline.phases import p13_embeddings

                with _phase_scope("p13_embeddings"):
                    p13_embeddings.run(store)
            except ImportError:
                if config.strict:
                    raise
                console.print("[yellow]sentence-transformers not installed, skipping embeddings[/]")

        progress.add_task("Running plugin hooks...", total=None)

    return files, parsed


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def run_full_pipeline(config: RunConfig) -> dict:
    """Run the full graph-build pipeline against a repository.

    Phases p01–p13 build the graph from scratch.  All analysis and export work
    is performed by plugin hooks fired at the end — no direct p15–p20 calls.
    """
    from repograph.pipeline.incremental import IncrementalDiff
    from repograph.pipeline.sync_state import clear_sync_lock, write_sync_lock
    from repograph.pipeline.health import (
        build_health_failure_report, build_health_report, write_health_json,
    )

    _run_id = new_run_id()
    _validate_run_config_paths(config)
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
        files, parsed = _run_full_build_steps(config, store)
        _run_experimental_pipeline_phases(config, store, parsed)
        hook_summary = _fire_hooks(config, store, parsed)
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
    from repograph.pipeline.phases import p03b_framework_tags, p05c_http_calls, p06b_layer_classify
    from repograph.pipeline.sync_state import clear_sync_lock, write_sync_lock
    from repograph.pipeline.health import (
        build_health_failure_report, build_health_report, write_health_json,
    )

    _run_id = new_run_id()
    _validate_run_config_paths(config)
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

            _ensure_scheduler_bootstrapped()
            parsed = p03_parse.run(reparse_files, store, symbol_table)
            p03b_framework_tags.run(parsed, store)
            _run_phases_parallel(
                config, parsed, store, symbol_table,
                include_git=False,
                reparse_paths=reparse_paths,
            )

        store.clear_pathways()
        store.clear_processes()

        # H4: try partial community update for small change sets; fall back to full re-run.
        community_snapshot = p09_communities.load_community_snapshot(config.repograph_dir)
        _did_partial = False
        if community_snapshot and reparse_paths:
            changed_fns = _get_function_ids_in_paths(store, reparse_paths)
            total = community_snapshot.get("total_functions", 0)
            if total > 0 and len(changed_fns) < total * p09_communities._PARTIAL_RERUN_THRESHOLD:
                _did_partial = p09_communities.run_partial(
                    store, changed_fns, min_community_size=config.min_community_size,
                )

        if not _did_partial:
            store.clear_communities()
            p09_communities.run(store, min_community_size=config.min_community_size)

        p09_communities.save_community_snapshot(config.repograph_dir, store)
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


def run_full_pipeline_with_runtime_overlay(
    config: RunConfig,
    *,
    pytest_targets: list[str] | None = None,
) -> dict:
    """Run a full rebuild plus automatic traced tests in one command.

    The dynamic phase is intentionally file-clean: no tracked ``conftest.py`` or
    ``sitecustomize.py`` is written into the repository. Runtime traces are
    collected via a temporary bootstrap and merged directly into the rebuilt DB.
    """
    from repograph.graph_store.store import _delete_db_dir
    from repograph.pipeline.health import (
        build_health_failure_report,
        build_health_report,
        write_health_json,
    )
    from repograph.pipeline.incremental import IncrementalDiff
    from repograph.pipeline.sync_state import clear_sync_lock, write_sync_lock
    from repograph.runtime.ephemeral import run_command_under_trace

    _run_id = new_run_id()
    _validate_run_config_paths(config)
    init_observability(ObservabilityConfig(
        log_dir=Path(config.repograph_dir) / "logs",
        run_id=_run_id,
    ))
    set_obs_context(phase="full_sync_runtime_overlay")
    _logger.info("full pipeline with runtime overlay started", repo_root=config.repo_root, run_id=_run_id)

    write_sync_lock(config.repograph_dir, mode="full", repo_root=config.repo_root, phase="starting")
    store: GraphStore | None = None
    files: list[FileRecord] = []
    parsed: list[ParsedFile] = []
    last_stats: dict[str, int] | None = None
    static_hook_summary: dict[str, Any] = {}
    final_hook_summary: dict[str, Any] = {}
    dynamic_analysis: dict[str, Any] = {
        "requested": True,
        "executed": False,
        "resolution": "",
        "test_command": [],
        "skipped_reason": "",
        "pytest_exit_code": None,
        "trace_file_count": 0,
        "trace_record_count": 0,
        "overlay_persisted_functions": 0,
        "dynamic_findings_count": 0,
    }

    try:
        _clear_runtime_trace_dir(config.repograph_dir)

        db_path = os.path.join(config.repograph_dir, "graph.db")
        console.print("[cyan]Step 1/3: full static pipeline...[/]")
        _delete_db_dir(db_path)
        store = GraphStore(db_path)
        store.initialize_schema()
        with _phase_scope("dynamic_full.step1_static_rebuild"):
            files, parsed = _run_full_build_steps(config, store)
            _run_experimental_pipeline_phases(config, store, parsed)
            static_hook_summary = _fire_hooks(
                config,
                store,
                parsed,
                run_graph_built=True,
                run_dynamic=False,
                run_evidence=False,
                run_export=False,
            )
        IncrementalDiff(config.repograph_dir).save_index({fr.path: fr for fr in files})
        last_stats = store.get_stats()
        store.close()
        store = None

        if pytest_targets is not None:
            test_command = [sys.executable, "-m", "pytest", *pytest_targets]
            resolution = "deprecated_alias"
        else:
            test_command, resolution = _resolve_sync_test_command(config.repo_root)

        dynamic_analysis["resolution"] = resolution or ""
        dynamic_analysis["test_command"] = list(test_command or [])

        if not test_command:
            dynamic_analysis["skipped_reason"] = "no_pytest_signal"
            console.print(
                "[yellow]Dynamic analysis skipped:[/] no pytest configuration was detected in "
                "[bold]pyproject.toml[/]. Add [bold]sync_test_command[/] to "
                "[bold]repograph.index.yaml[/] to opt in."
            )
        else:
            dynamic_analysis["executed"] = True
            console.print(
                f"[cyan]Step 2/3: {' '.join(test_command)}[/] "
                "[dim](ephemeral tracing enabled)[/]"
            )
            with _phase_scope(
                "dynamic_full.step2_traced_tests",
                resolution=dynamic_analysis["resolution"],
                command_len=len(test_command),
            ):
                result = run_command_under_trace(
                    test_command,
                    repo_root=config.repo_root,
                    repograph_dir=config.repograph_dir,
                    session_name="pytest",
                )
            dynamic_analysis["pytest_exit_code"] = int(result.returncode)
            inventory = _trace_inventory(config.repograph_dir)
            dynamic_analysis.update(inventory)
            if inventory["trace_file_count"] > 0:
                console.print(
                    f"[green]{inventory['trace_file_count']} trace file(s), "
                    f"{inventory['trace_record_count']:,} total records.[/]"
                )
            else:
                console.print("[yellow]No runtime trace files were produced by the test command.[/]")
            if result.returncode != 0:
                msg = f"test command exited with code {result.returncode}"
                if config.strict:
                    raise RuntimeError(msg)
                console.print(
                    f"[yellow]{msg} — continuing with any collected traces "
                    "(use [bold]--strict[/] on sync to abort on test failures)[/]"
                )

        console.print("[cyan]Step 3/3: finalizing evidence, exports, and runtime overlay...[/]")
        store = GraphStore(db_path)
        store.initialize_schema()
        with _phase_scope(
            "dynamic_full.step3_finalize_overlay",
            trace_file_count=dynamic_analysis["trace_file_count"],
        ):
            final_hook_summary = _fire_hooks(
                config,
                store,
                [],
                run_graph_built=False,
                run_dynamic=dynamic_analysis["trace_file_count"] > 0,
                run_evidence=True,
                run_export=True,
            )
        dynamic_analysis["dynamic_findings_count"] = int(
            final_hook_summary.get("dynamic_findings_count") or 0
        )
        dynamic_analysis["overlay_persisted_functions"] = _count_valid_runtime_observations(store)
        last_stats = store.get_stats()
        sync_mode = "full_with_runtime_overlay" if dynamic_analysis["trace_file_count"] > 0 else "full"
        write_health_json(
            config.repograph_dir,
            build_health_report(
                store,
                last_stats,
                repo_root=config.repo_root,
                repograph_dir=config.repograph_dir,
                sync_mode=sync_mode,
                files_walked=len(files),
                strict=config.strict,
                hook_summary=_merge_hook_summaries(static_hook_summary, final_hook_summary),
                dynamic_analysis=dynamic_analysis,
            ),
        )
        return last_stats

    except BaseException as exc:
        partial = last_stats
        if partial is None and store is not None:
            try:
                partial = store.get_stats()
            except Exception as stats_exc:
                _logger.warning("store.get_stats() failed during error recovery", exc_msg=str(stats_exc))
        error_phase = "tests" if dynamic_analysis.get("pytest_exit_code") not in (None, 0) else "pipeline"
        try:
            write_health_json(
                config.repograph_dir,
                build_health_failure_report(
                    repo_root=config.repo_root,
                    repograph_dir=config.repograph_dir,
                    sync_mode="full_with_runtime_overlay" if dynamic_analysis.get("executed") else "full",
                    error_phase=error_phase,
                    error_message=f"{type(exc).__name__}: {exc}",
                    strict=config.strict,
                    partial_stats=partial,
                    dynamic_analysis=dynamic_analysis,
                ),
            )
        except Exception as health_exc:
            _logger.warning("write_health_json failed during error recovery", exc_msg=str(health_exc))
        _logger.error(
            "full pipeline with runtime overlay failed",
            exc_type=type(exc).__name__,
            exc_msg=str(exc),
        )
        console.print(f"[red bold]Full sync failed:[/] {exc}")
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
    """Deprecated compatibility wrapper for the old ``--full-with-tests`` path."""
    return run_full_pipeline_with_runtime_overlay(config, pytest_targets=pytest_targets)
