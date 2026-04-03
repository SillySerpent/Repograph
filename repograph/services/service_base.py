"""Shared RepoGraph service base helpers and lifecycle management."""
from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any, Callable, Final, Protocol, TypeAlias

from repograph.observability import (
    ObservableMixin,
    active_run_id,
    ensure_observability_session,
    shutdown_observability,
)
from repograph.runtime.session import RuntimeAttachPolicy
from repograph.settings import resolve_runtime_settings


def _apply_limit(rows: list[Any], limit: int | None) -> list[Any]:
    if limit is None:
        return list(rows)
    return list(rows[:limit])


def _limit_for_metadata(limit: int | None) -> int:
    return -1 if limit is None else int(limit)


class _EntryPointLimitUnset:
    """Internal sentinel for omitted entry-point limits."""

    __slots__ = ()


EntryPointLimitArg: TypeAlias = int | None | _EntryPointLimitUnset

_ENTRY_POINT_LIMIT_UNSET: Final[_EntryPointLimitUnset] = _EntryPointLimitUnset()


class RepoGraphServiceProtocol(Protocol):
    """Structural contract shared across the composed service mixins."""

    repo_path: str
    repograph_dir: str
    include_git: bool
    logger: Any

    def span(self, operation: str, **metadata: Any) -> Any: ...
    def _ensure_observability_session(self) -> None: ...
    def _is_initialized(self) -> bool: ...
    def _get_store(self) -> Any: ...
    def _log_dir(self) -> Path: ...
    def _resolve_run_dir(self, log_dir: Path, run_id: str | None) -> Path | None: ...
    def status(self) -> dict: ...
    def pathways(
        self,
        min_confidence: float = 0.0,
        include_tests: bool = False,
    ) -> list[dict]: ...
    def entry_points(
        self,
        limit: EntryPointLimitArg = _ENTRY_POINT_LIMIT_UNSET,
    ) -> list[dict]: ...
    def dead_code(self, min_tier: str = "probably_dead") -> list[dict]: ...
    def duplicates(self, min_severity: str = "medium") -> list[dict]: ...
    def doc_warnings(
        self,
        severity: str | None = None,
        *,
        min_severity: str | None = None,
    ) -> list[dict]: ...
    def modules(self) -> list[dict]: ...
    def invariants(
        self,
        inv_type: str | None = None,
        file_path: str | None = None,
    ) -> list[dict]: ...
    def config_registry(self, key: str | None = None) -> dict: ...
    def config_registry_diagnostics(self) -> dict: ...
    def test_coverage(self) -> list[dict]: ...
    def test_coverage_any_call(self) -> list[dict]: ...
    def communities(self) -> list[dict]: ...
    def run_analyzer_plugin(self, plugin_id: str, **kwargs: Any) -> Any: ...
    def run_evidence_plugin(self, plugin_id: str, **kwargs: Any) -> Any: ...
    def run_exporter_plugin(self, plugin_id: str, **kwargs: Any) -> Any: ...
    def contract_rules(self) -> list[dict]: ...
    def boundary_shortcuts(self) -> list[dict]: ...
    def architecture_conformance(self) -> list[dict]: ...
    def class_roles(self) -> list[dict]: ...
    def config_flow(self) -> dict: ...
    def module_component_signals(self) -> list[dict]: ...
    def runtime_overlay_summary(self) -> dict: ...
    def observed_runtime_findings(self) -> dict: ...
    def report_surfaces(self) -> dict: ...


def _entry_point_limit_metadata_value(
    repo_path: str,
    limit: EntryPointLimitArg = _ENTRY_POINT_LIMIT_UNSET,
) -> int | str:
    if isinstance(limit, _EntryPointLimitUnset):
        return int(resolve_runtime_settings(repo_path).entry_point_limit)
    return "all" if limit is None else int(limit)


def _entry_points_metadata(
    self: RepoGraphServiceProtocol,
    limit: EntryPointLimitArg = _ENTRY_POINT_LIMIT_UNSET,
) -> dict[str, int | str]:
    return {"limit": _entry_point_limit_metadata_value(self.repo_path, limit)}


def _full_report_metadata(
    self: RepoGraphServiceProtocol,
    max_pathways: int | None = 10,
    max_dead: int | None = 20,
    entry_point_limit: EntryPointLimitArg = _ENTRY_POINT_LIMIT_UNSET,
    max_config_keys: int | None = 30,
    max_communities: int | None = 20,
) -> dict[str, int]:
    return {
        "max_pathways": _limit_for_metadata(max_pathways),
        "max_dead": _limit_for_metadata(max_dead),
        "entry_point_limit": (
            int(resolve_runtime_settings(self.repo_path).entry_point_limit)
            if isinstance(entry_point_limit, _EntryPointLimitUnset)
            else _limit_for_metadata(entry_point_limit)
        ),
        "max_config_keys": _limit_for_metadata(max_config_keys),
        "max_communities": _limit_for_metadata(max_communities),
    }


def _add_result_metadata(span_ctx: Any, result: Any) -> None:
    """Attach small, non-sensitive result-shape metadata to a service span."""
    if result is None:
        span_ctx.add_metadata(result_found=False)
        return
    if isinstance(result, list):
        span_ctx.add_metadata(result_count=len(result))
        return
    if isinstance(result, dict):
        meta: dict[str, Any] = {"result_keys": len(result)}
        if "error" in result:
            meta["has_error"] = bool(result.get("error"))
        if "initialized" in result:
            meta["initialized"] = bool(result.get("initialized"))
        span_ctx.add_metadata(**meta)
        return
    if isinstance(result, str):
        span_ctx.add_metadata(result_len=len(result))


def _observed_service_call(
    operation: str,
    *,
    metadata_fn: Callable[..., dict[str, Any]] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Wrap a public service method with an observability session and span."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(self: RepoGraphServiceProtocol, *args: Any, **kwargs: Any) -> Any:
            self._ensure_observability_session()
            metadata: dict[str, Any] = {}
            if metadata_fn is not None:
                try:
                    metadata = metadata_fn(self, *args, **kwargs) or {}
                except Exception as exc:
                    self.logger.warning(
                        "service observability metadata failed",
                        operation=operation,
                        exc_type=type(exc).__name__,
                        exc_msg=str(exc),
                    )
            with self.span(operation, **metadata) as span_ctx:
                result = fn(self, *args, **kwargs)
                _add_result_metadata(span_ctx, result)
                return result

        return wrapper

    return decorator


class RepoGraphServiceBase(ObservableMixin):
    """Shared lifecycle and storage behavior for the RepoGraph service facade."""

    _obs_subsystem = "services"

    def __init__(
        self,
        repo_path: str | None = None,
        repograph_dir: str | None = None,
        include_git: bool | None = None,
    ) -> None:
        self.repo_path = os.path.abspath(repo_path or os.getcwd())
        self.repograph_dir = repograph_dir or os.path.join(self.repo_path, ".repograph")

        if include_git is None:
            include_git = resolve_runtime_settings(self.repo_path).include_git
        self.include_git = include_git

        self._store: Any = None
        self._owned_obs_run_id: str | None = None

    def _ensure_observability_session(self) -> None:
        """Start a read-session log sink when the caller has not already done so."""
        started_run_id = ensure_observability_session(Path(self.repograph_dir) / "logs")
        if started_run_id is not None:
            self._owned_obs_run_id = started_run_id
            self.logger.info(
                "service observability session started",
                repo_root=self.repo_path,
                run_id=started_run_id,
            )

    def _shutdown_owned_observability_session(self) -> None:
        """Stop the service-owned observability session, if it is still active."""
        if self._owned_obs_run_id and active_run_id() == self._owned_obs_run_id:
            self.logger.info(
                "service observability session shutdown",
                run_id=self._owned_obs_run_id,
            )
            shutdown_observability()
        self._owned_obs_run_id = None

    def sync(
        self,
        full: bool = False,
        include_embeddings: bool | None = None,
        max_context_tokens: int | None = None,
        strict: bool = False,
        continue_on_error: bool = True,
        attach_policy: RuntimeAttachPolicy | None = None,
    ) -> dict:
        """Index or re-index the repository."""
        from repograph.pipeline.runner import (
            RunConfig,
            run_full_pipeline,
            run_full_pipeline_with_runtime_overlay,
            run_incremental_pipeline,
        )

        os.makedirs(self.repograph_dir, exist_ok=True)
        resolved = resolve_runtime_settings(
            self.repo_path,
            include_git=self.include_git,
            include_embeddings=include_embeddings,
            max_context_tokens=max_context_tokens,
        )
        config = RunConfig(
            repo_root=self.repo_path,
            repograph_dir=self.repograph_dir,
            include_git=resolved.include_git,
            include_embeddings=resolved.include_embeddings,
            full=full,
            max_context_tokens=resolved.max_context_tokens,
            strict=strict,
            continue_on_error=continue_on_error,
            min_community_size=resolved.min_community_size,
            git_days=resolved.git_days,
            runtime_attach_policy=attach_policy or resolved.settings.sync_runtime_attach_policy,
        )
        self._store = None

        if full or not self._is_initialized():
            if resolved.auto_dynamic_analysis:
                return run_full_pipeline_with_runtime_overlay(config)
            return run_full_pipeline(config)
        return run_incremental_pipeline(config)

    def _is_initialized(self) -> bool:
        db = os.path.join(self.repograph_dir, "graph.db")
        wal = os.path.join(self.repograph_dir, "graph.db.wal")
        return os.path.exists(db) or os.path.exists(wal)

    def _get_store(self) -> Any:
        if self._store is None:
            from repograph.graph_store.store import GraphStore

            db = os.path.join(self.repograph_dir, "graph.db")
            with self.span("service_open_store", db_path=db):
                self._store = GraphStore(db)
                self._store.prepare_read_state()
            self.logger.debug("service store opened", db_path=db)
        return self._store

    def close(self) -> None:
        """Explicitly close the database connection."""
        if self._store is not None:
            with self.span("service_close_store"):
                self._store.close()
                self._store = None
        self._shutdown_owned_observability_session()

    def _log_dir(self) -> Path:
        return Path(self.repograph_dir) / "logs"

    def _resolve_run_dir(self, log_dir: Path, run_id: str | None) -> Path | None:
        if not log_dir.exists():
            return None
        if run_id:
            candidate = log_dir / run_id
            return candidate if candidate.is_dir() else None
        latest = log_dir / "latest"
        if latest.is_symlink() and latest.exists():
            return latest.resolve()
        dirs = sorted(
            (d for d in log_dir.iterdir() if d.is_dir()),
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        return dirs[0] if dirs else None

    def __enter__(self) -> Any:
        self._ensure_observability_session()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"RepoGraphService(repo={self.repo_path!r})"


__all__ = [
    "EntryPointLimitArg",
    "RepoGraphServiceProtocol",
    "RepoGraphServiceBase",
    "_ENTRY_POINT_LIMIT_UNSET",
    "_apply_limit",
    "_entry_points_metadata",
    "_full_report_metadata",
    "_limit_for_metadata",
    "_observed_service_call",
]
