"""Static graph-build steps and optional phase execution.

This module owns the direct phase execution path used by both full and
incremental syncs. It intentionally excludes hook execution and runtime-mode
orchestration so the build steps stay readable on their own.
"""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from repograph.core.models import FileRecord, ParsedFile
from repograph.graph_store.store import GraphStore
from repograph.observability import make_thread_context
from repograph.parsing.symbol_table import SymbolTable

from .config import RunConfig
from .shared import (
    console,
    ensure_scheduler_bootstrapped,
    handle_optional_phase_failure,
    phase_scope,
)

__all__ = [
    "count_valid_runtime_observations",
    "get_function_ids_in_paths",
    "run_experimental_pipeline_phases",
    "run_full_build_steps",
    "run_phases_parallel",
]


def get_function_ids_in_paths(store: GraphStore, file_paths: set[str]) -> set[str]:
    """Return function IDs whose file path is in ``file_paths``."""
    if not file_paths:
        return set()
    try:
        rows = store.query(
            "MATCH (f:Function) WHERE f.file_path IN $fps RETURN f.id",
            {"fps": list(file_paths)},
        )
        return {row[0] for row in rows}
    except Exception:
        return set()


def run_phases_parallel(
    config: RunConfig,
    parsed: list[ParsedFile],
    store: GraphStore,
    symbol_table: SymbolTable,
    *,
    include_git: bool = False,
    reparse_paths: set[str] | None = None,
) -> None:
    """Run dependency-ordered mid-pipeline phases with parallel waves.

    `p04_imports` must complete first because `p05_calls` depends on resolved
    import information. After that barrier, the remaining phases can run in
    parallel because they consume immutable parse data and write disjoint
    relationship families.
    """
    from repograph.pipeline.phases import (
        p04_imports,
        p05_calls,
        p05b_callbacks,
        p05c_http_calls,
        p06_heritage,
        p06b_layer_classify,
        p07_variables,
        p08_types,
    )

    try:
        with phase_scope("p04_imports", parsed_files=len(parsed)):
            p04_imports.run(parsed, store, symbol_table, config.repo_root)
    except BaseException as exc:
        handle_optional_phase_failure(config, "phase p04_imports", exc)

    phase_tasks: dict[str, Callable[[], object]] = {
        "p05_calls": lambda: p05_calls.run(parsed, store, symbol_table),
        "p05b_callbacks": lambda: p05b_callbacks.run(parsed, store, symbol_table),
        "p05c_http": lambda: p05c_http_calls.run(parsed, store),
        "p06_heritage": lambda: p06_heritage.run(parsed, store, symbol_table),
        "p06b_layers": lambda: p06b_layer_classify.run(parsed, store),
        "p07_variables": lambda: (
            p07_variables.run(parsed, store, reparse_paths=reparse_paths)
            if reparse_paths is not None
            else p07_variables.run(parsed, store)
        ),
        "p08_types": lambda: p08_types.run(parsed, store, symbol_table),
    }
    if include_git:
        from repograph.pipeline.phases import p12_coupling

        phase_tasks["p12_coupling"] = lambda: p12_coupling.run(
            store,
            config.repo_root,
            days=config.git_days,
        )

    failures: list[tuple[str, BaseException]] = []

    def _wrap_phase(name: str, fn: Callable[[], object]) -> Callable[[], object]:
        def _run() -> object:
            with phase_scope(name, parsed_files=len(parsed)):
                return fn()

        return _run

    with ThreadPoolExecutor(max_workers=len(phase_tasks)) as executor:
        future_to_name = {
            executor.submit(make_thread_context().run, _wrap_phase(name, fn)): name
            for name, fn in phase_tasks.items()
        }
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            exc = future.exception()
            if exc:
                failures.append((name, exc))

    for name, exc in failures:
        handle_optional_phase_failure(config, f"phase {name}", exc)


def run_experimental_pipeline_phases(
    config: RunConfig,
    store: GraphStore,
    parsed: list[ParsedFile],
) -> None:
    """Run optional SPI phases after the static graph build, before hooks."""
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
            handle_optional_phase_failure(
                config,
                f"experimental pipeline phase {phase.phase_id}",
                exc,
            )


def count_valid_runtime_observations(store: GraphStore) -> int:
    """Count functions whose persisted runtime observations match current source."""
    total = 0
    for fn in store.get_all_functions():
        if fn.get("runtime_observed") and (fn.get("runtime_observed_for_hash") or "") == (
            fn.get("source_hash") or ""
        ):
            total += 1
    return total


def run_full_build_steps(
    config: RunConfig,
    store: GraphStore,
) -> tuple[list[FileRecord], list[ParsedFile]]:
    """Execute the full static graph-build phases and return ``(files, parsed)``."""
    from repograph.pipeline.phases import (
        p01_walk,
        p02_structure,
        p03_parse,
        p09_communities,
        p10_processes,
    )
    from repograph.pipeline.phases import p03b_framework_tags

    symbol_table = SymbolTable()
    ensure_scheduler_bootstrapped()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Phase 1: Walking repository...", total=None)
        with phase_scope("p01_walk", repo_root=config.repo_root) as phase_span:
            files = p01_walk.run(config.repo_root)
            phase_span.add_metadata(file_count=len(files))
        progress.update(task, description=f"Phase 1: Found {len(files)} files")

        progress.add_task("Phase 2: Building folder structure...", total=None)
        with phase_scope("p02_structure", file_count=len(files)):
            p02_structure.run(files, store, config.repo_root)

        task3 = progress.add_task(f"Phase 3: Parsing {len(files)} files...", total=None)
        with phase_scope("p03_parse", file_count=len(files)) as phase_span:
            parsed = p03_parse.run(files, store, symbol_table)
            phase_span.add_metadata(parsed_files=len(parsed))
        progress.update(task3, description=f"Phase 3: Parsed {len(parsed)} files")

        progress.add_task("Phase 3b: Applying framework tags...", total=None)
        with phase_scope("p03b_framework_tags", parsed_files=len(parsed)):
            p03b_framework_tags.run(parsed, store)

        progress.add_task("Phases 4-8: Resolving relationships (parallel)...", total=None)
        with phase_scope(
            "p04_to_p08_parallel",
            parsed_files=len(parsed),
            include_git=config.include_git,
        ):
            run_phases_parallel(
                config,
                parsed,
                store,
                symbol_table,
                include_git=config.include_git,
            )

        progress.add_task("Phase 9: Detecting communities...", total=None)
        with phase_scope("p09_communities", min_community_size=config.min_community_size):
            p09_communities.run(store, min_community_size=config.min_community_size)
        p09_communities.save_community_snapshot(config.repograph_dir, store)

        progress.add_task("Phase 10: Scoring entry points...", total=None)
        with phase_scope("p10_processes"):
            p10_processes.run(store)

        if config.include_embeddings:
            progress.add_task("Phase 13: Building embeddings...", total=None)
            try:
                from repograph.pipeline.phases import p13_embeddings

                with phase_scope("p13_embeddings"):
                    p13_embeddings.run(store)
            except ImportError:
                if config.strict:
                    raise
                console.print("[yellow]sentence-transformers not installed, skipping embeddings[/]")

        progress.add_task("Running plugin hooks...", total=None)

    return files, parsed
