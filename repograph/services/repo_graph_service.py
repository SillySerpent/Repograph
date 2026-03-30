"""RepoGraph Python API — single entry point for all operations.

Usage
-----
    from repograph.api import RepoGraph

    rg = RepoGraph("/path/to/your/repo")

    # Index the repo (full rebuild)
    stats = rg.sync(full=True)

    # Query
    print(rg.status())
    print(rg.entry_points())
    print(rg.dead_code())
    print(rg.pathways())
    print(rg.get_pathway("my_flow"))
    print(rg.search("rate limiting middleware"))
    print(rg.impact("validate_credentials"))
    print(rg.node("src/services/auth.py"))
    print(rg.get_all_files())
"""
from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any, Callable

from repograph.config import DEFAULT_CONTEXT_TOKENS as _DEFAULT_CONTEXT_TOKENS
from repograph.graph_store.store_queries_analytics import (
    ANY_CALL_TEST_COVERAGE_DEFINITION,
    ENTRY_POINT_TEST_COVERAGE_DEFINITION,
)
from repograph.core.evidence import summarize_findings
from repograph.observability import (
    ObservableMixin,
    active_run_id,
    ensure_observability_session,
    shutdown_observability,
)


def _build_report_warnings(
    *,
    health: dict,
    pathways_total: int,
    pathways_shown: int,
    communities_total: int,
    communities_shown: int,
    cfg_top: dict,
    cfg_diag: dict,
) -> list[str]:
    warnings: list[str] = []
    if health.get("sync_mode") == "incremental_traces_only":
        warnings.append(
            "Report reflects a trace-only incremental refresh; run a full sync for a full static rebuild snapshot."
        )
    dyn = health.get("dynamic_analysis") or {}
    if dyn.get("requested") and not dyn.get("executed"):
        reason = str(dyn.get("skipped_reason") or "").strip() or "unspecified"
        warnings.append(
            "Dynamic analysis was requested for the last full sync but skipped "
            f"({reason}). Add sync_test_command or pytest config if you want runtime overlay."
        )
    if health.get("status") == "degraded":
        warnings.append(
            "Last sync completed with degraded health (one or more optional hooks failed)."
        )
    if pathways_total > pathways_shown:
        warnings.append(
            f"Pathways are capped in this report ({pathways_shown}/{pathways_total} shown)."
        )
    if communities_total > communities_shown:
        warnings.append(
            f"Communities are capped in this report ({communities_shown}/{communities_total} shown)."
        )
    if not cfg_top and cfg_diag.get("status"):
        warnings.append(
            f"Config registry empty ({cfg_diag.get('status')}); inspect config_registry_diagnostics for scan details."
        )
    return warnings


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
        def wrapper(self: "RepoGraphService", *args: Any, **kwargs: Any) -> Any:
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


class RepoGraphService(ObservableMixin):
    """High-level API for indexing and querying a repository with RepoGraph.

    Parameters
    ----------
    repo_path:
        Absolute or relative path to the repository root.  Defaults to the
        current working directory.
    repograph_dir:
        Where to store the RepoGraph index.  Defaults to ``<repo_path>/.repograph``.
    include_git:
        Whether to analyse git history for co-change coupling (Phase 12).
        Defaults to True if a ``.git`` directory is present, False otherwise.
    """

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
            include_git = os.path.isdir(os.path.join(self.repo_path, ".git"))
        self.include_git = include_git

        self._store: Any = None  # lazy-opened
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
            self.logger.info("service observability session shutdown", run_id=self._owned_obs_run_id)
            shutdown_observability()
        self._owned_obs_run_id = None

    # ------------------------------------------------------------------
    # Core pipeline
    # ------------------------------------------------------------------

    def sync(
        self,
        full: bool = False,
        include_embeddings: bool = False,
        max_context_tokens: int = _DEFAULT_CONTEXT_TOKENS,
        strict: bool = False,
        continue_on_error: bool = True,
    ) -> dict:
        """Index (or re-index) the repository.

        Parameters
        ----------
        full:
            Force a complete rebuild from scratch.  When False (default),
            runs an incremental sync that only re-processes changed files.
            If no previous index exists, a full rebuild runs automatically.
        include_embeddings:
            Generate vector embeddings for semantic search (requires
            ``sentence-transformers``).  Disabled by default.
        max_context_tokens:
            Token budget for generated pathway context documents.
        strict:
            When True, optional phases (duplicate detection, pathway context,
            agent guide, doc check, embeddings) raise on failure instead of
            logging a warning.
        continue_on_error:
            When False, the first optional-phase failure aborts the sync.

        Returns
        -------
        dict
            Stats dict with counts for files, functions, classes, pathways, etc.
        """
        from repograph.pipeline.runner import RunConfig, run_full_pipeline, run_incremental_pipeline

        os.makedirs(self.repograph_dir, exist_ok=True)
        config = RunConfig(
            repo_root=self.repo_path,
            repograph_dir=self.repograph_dir,
            include_git=self.include_git,
            include_embeddings=include_embeddings,
            full=full,
            max_context_tokens=max_context_tokens,
            strict=strict,
            continue_on_error=continue_on_error,
        )
        self._store = None  # invalidate cached handle after rebuild

        if full or not self._is_initialized():
            stats = run_full_pipeline(config)
        else:
            stats = run_incremental_pipeline(config)

        return stats

    # ------------------------------------------------------------------
    # Status / overview
    # ------------------------------------------------------------------

    @_observed_service_call("service_status")
    def status(self) -> dict:
        """Return index health: node counts, pathway count, last-sync time, stale flags.

        Returns
        -------
        dict with keys: files, functions, classes, variables, imports,
        pathways, communities, initialized, last_sync.
        """
        if not self._is_initialized():
            return {"initialized": False}

        store = self._get_store()
        stats = store.get_stats()
        stats["initialized"] = True

        # Add last-sync time from meta.json if present
        meta_path = os.path.join(self.repograph_dir, "meta.json")
        if os.path.exists(meta_path):
            import json
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                stats["last_sync"] = meta.get("generated_at", "unknown")
                stats["repo"] = meta.get("repo_name", os.path.basename(self.repo_path))
            except Exception:
                pass

        from repograph.pipeline.health import read_health_json

        h = read_health_json(self.repograph_dir)
        if h:
            stats["health"] = {
                "contract_version": h.get("contract_version"),
                "sync_mode": h.get("sync_mode"),
                "call_edges_total": h.get("call_edges_total"),
                "generated_at": h.get("generated_at"),
                "strict": h.get("strict"),
                "status": h.get("status"),
                "error_phase": h.get("error_phase"),
                "error_message": h.get("error_message"),
                "partial_completion": h.get("partial_completion"),
                "hook_summary": h.get("hook_summary"),
                "dynamic_analysis": h.get("dynamic_analysis") or {},
            }

        return stats

    # ------------------------------------------------------------------
    # Plugin manifests and wrappers
    # ------------------------------------------------------------------

    def plugin_manifests(self) -> dict[str, list[dict]]:
        """Return manifests for built-in parser/framework/evidence/demand-analyzer/exporter plugins."""
        from repograph.plugins.features import built_in_plugin_manifests

        return built_in_plugin_manifests()

    def run_analyzer_plugin(self, plugin_id: str, **kwargs):
        """Run a registered demand-side analyzer plugin against this service context."""
        from repograph.plugins.features import run_analyzer

        return run_analyzer(plugin_id, service=self, **kwargs)

    def run_evidence_plugin(self, plugin_id: str, **kwargs):
        """Run a registered evidence producer against this service context."""
        from repograph.plugins.features import run_evidence_producer

        return run_evidence_producer(plugin_id, service=self, **kwargs)

    def run_exporter_plugin(self, plugin_id: str, **kwargs):
        """Run a registered exporter plugin against this service context."""
        from repograph.plugins.features import run_exporter

        return run_exporter(plugin_id, service=self, **kwargs)


    def rule_pack_config(self) -> dict:
        """Return enabled rule-pack registration/config for current built-ins."""
        from repograph.plugins.rules import get_rule_pack_config
        return get_rule_pack_config(self).as_dict()


    def save_rule_pack_config(self, packs: dict[str, dict]) -> dict:
        """Persist repo-local rule-pack overrides and return the resolved config."""
        from repograph.plugins.rules import save_rule_pack_overrides
        return save_rule_pack_overrides(self, packs).as_dict()
    
    def finding_statuses(self) -> dict:
        """Return persisted finding statuses for the current repo."""
        from repograph.plugins.rules import get_finding_status_store
        return get_finding_status_store(self).as_dict()
    
    def update_finding_status(self, finding_id: str, status: str, note: str | None = None) -> dict:
        """Persist an approval-oriented status for a finding."""
        from repograph.plugins.rules import update_finding_status
        return update_finding_status(self, finding_id, status, note)

    def contract_rules(self) -> list[dict]:
        """Return contract-oriented rule findings such as private surface bypasses and UI config reads."""
        return self.run_analyzer_plugin("demand_analyzer.contract_rules")

    def boundary_shortcuts(self) -> list[dict]:
        """Return likely cross-layer shortcut findings such as UI/API directly reaching DB/domain layers."""
        return self.run_analyzer_plugin("demand_analyzer.boundary_shortcuts")

    def boundary_rules(self) -> list[dict]:
        """Compatibility wrapper returning all boundary-style rules."""
        return [*self.contract_rules(), *self.boundary_shortcuts()]

    def architecture_conformance(self) -> list[dict]:
        """Return architecture shortcut and boundary findings meant for Meridian verification flows."""
        return self.run_analyzer_plugin("demand_analyzer.architecture_conformance")

    def class_roles(self) -> list[dict]:
        """Return inferred class-role classifications for structural review and Meridian import flows."""
        return self.run_analyzer_plugin("demand_analyzer.class_roles")

    def decomposition_signals(self) -> list[dict]:
        """Return heuristic split/modulation candidates for files and classes."""
        return self.run_analyzer_plugin("demand_analyzer.decomposition_signals")

    def config_flow(self) -> dict:
        """Return inferred config key declarations and reads across the repo."""
        out = self.run_analyzer_plugin("demand_analyzer.config_flow")
        if isinstance(out, list):
            if out and isinstance(out[0], dict):
                return out[0]
            return {}
        if isinstance(out, dict):
            return out
        return {}

    def module_component_signals(self) -> list[dict]:
        """Return inferred module roles and component-candidate signals for files."""
        return self.run_analyzer_plugin("demand_analyzer.module_component_signals")

    def runtime_overlay_summary(self) -> dict:
        """Return observed/runtime overlay metadata without replacing static evidence."""
        return self.run_exporter_plugin("exporter.runtime_overlay_summary")

    def observed_runtime_findings(self) -> dict:
        """Return consumed/normalized observed runtime findings from optional trace payloads."""
        return self.run_exporter_plugin("exporter.observed_runtime_findings")

    def report_surfaces(self) -> dict:
        """Return grouped report/meta surfaces for UI consumers."""
        return self.run_exporter_plugin("exporter.report_surfaces")

    def intelligence_snapshot(self) -> dict:
        """Return a Meridian-facing evidence snapshot with stable grouped sections."""
        from repograph.plugins.rules import summarize_rule_packs, get_rule_pack_config, annotate_finding_statuses, get_finding_status_store, summarize_finding_statuses
        pathways = self.pathways(min_confidence=0.4)
        dead = self.dead_code()[:30]
        config_flow = self.config_flow()
        status_store = get_finding_status_store(self)
        architecture_conformance = annotate_finding_statuses(self.architecture_conformance()[:20], store=status_store)
        contract_rules = annotate_finding_statuses(self.contract_rules()[:20], store=status_store)
        boundary_shortcuts = annotate_finding_statuses(self.boundary_shortcuts()[:20], store=status_store)
        class_roles = self.class_roles()
        module_signals = self.module_component_signals()
        runtime_overlay = self.runtime_overlay_summary()
        observed_runtime = self.observed_runtime_findings()
        report_surfaces = self.report_surfaces()
        rule_summary = summarize_findings(architecture_conformance)
        _rule_pack_cfg = get_rule_pack_config(self)
        rule_pack_config = _rule_pack_cfg.as_dict()
        rule_pack_summary = summarize_rule_packs(architecture_conformance, config=_rule_pack_cfg)
        rule_pack_findings: dict[str, dict[str, Any]] = {}
        for finding in architecture_conformance:
            pack = str(finding.get("rule_pack") or "unpacked")
            bucket = rule_pack_findings.setdefault(pack, {"count": 0, "top": []})
            bucket["count"] += 1
            if len(bucket["top"]) < 10:
                bucket["top"].append(finding)
        actionable_findings = sorted(architecture_conformance, key=lambda item: int(item.get("severity_score") or 0), reverse=True)[:20]
        evidence = {
            "config_flow": config_flow,
            "architecture_conformance": architecture_conformance,
            "rule_families": {
                "contract_rules": {"count": len(contract_rules), "top": contract_rules[:10]},
                "boundary_shortcuts": {"count": len(boundary_shortcuts), "top": boundary_shortcuts[:10]},
            },
            "class_roles": {
                "count": len(class_roles),
                "top": class_roles[:20],
            },
            "module_component_signals": {
                "count": len(module_signals),
                "top": module_signals[:20],
            },
            "runtime_overlay": runtime_overlay,
            "observed_runtime_findings": observed_runtime,
            "report_surfaces": report_surfaces,
            "rule_packs": rule_pack_summary,
            "rule_pack_config": rule_pack_config,
            "rule_pack_findings": rule_pack_findings,
            "actionable_findings": actionable_findings,
            "finding_statuses": status_store.as_dict(),
            "approval_summary": summarize_finding_statuses(architecture_conformance),
            "policies": {
                "boundary_rules": {
                    **rule_summary,
                    "overlay_mode": observed_runtime.get("overlay_mode", "augment_not_replace"),
                },
                "rule_families": {
                    "contract_rules": summarize_findings(contract_rules),
                    "boundary_shortcuts": summarize_findings(boundary_shortcuts),
                },
            },
        }
        return {
            "pathways": pathways,
            "dead_code": dead,
            "evidence": evidence,
            "config_flow": config_flow,
            "architecture_conformance": architecture_conformance,
            "report_surfaces": report_surfaces,
            "observed_runtime_findings": observed_runtime,
        }

    # ------------------------------------------------------------------
    # Pathways
    # ------------------------------------------------------------------

    @_observed_service_call(
        "service_pathways",
        metadata_fn=lambda self, min_confidence=0.0, include_tests=False: {
            "min_confidence": float(min_confidence),
            "include_tests": bool(include_tests),
        },
    )
    def pathways(
        self,
        min_confidence: float = 0.0,
        include_tests: bool = False,
    ) -> list[dict]:
        """Return all detected pathways, sorted by confidence descending.

        Parameters
        ----------
        min_confidence:
            Filter to pathways with confidence >= this value.
        include_tests:
            When False (default) pathways whose source is
            ``"auto_detected_test"`` are excluded.  Set True to see
            test-entry pathways alongside production ones.

        Returns
        -------
        list of dicts with keys: name, display_name, description,
        confidence, step_count, entry_function, source.
        """
        store = self._get_store()
        all_p = store.get_all_pathways()
        if not include_tests:
            all_p = [p for p in all_p if p.get("source") != "auto_detected_test"]
        filtered = [p for p in all_p if p.get("confidence", 0) >= min_confidence]
        # Sort by importance_score (relevance) desc, then confidence as tiebreaker.
        return sorted(
            filtered,
            key=lambda p: (-(p.get("importance_score") or 0.0), -(p.get("confidence") or 0.0)),
        )

    @_observed_service_call(
        "service_get_pathway",
        metadata_fn=lambda self, name: {"pathway_name": name},
    )
    def get_pathway(self, name: str) -> dict | None:
        """Return the full context document for a named pathway.

        Parameters
        ----------
        name:
            Pathway name (as returned by ``pathways()``).

        Returns
        -------
        dict with keys: name, display_name, description, confidence,
        step_count, context_doc, entry_function, source, variable_threads.
        Returns None if not found.
        """
        store = self._get_store()
        return store.get_pathway(name)

    @_observed_service_call(
        "service_pathway_steps",
        metadata_fn=lambda self, name: {"pathway_name": name},
    )
    def pathway_steps(self, name: str) -> list[dict]:
        """Return ordered execution steps for a named pathway.

        Returns
        -------
        list of dicts: function_name, file_path, line_start, line_end,
        step_order, role.
        """
        store = self._get_store()
        pathway = store.get_pathway(name)
        if pathway is None:
            return []
        return store.get_pathway_steps(pathway["id"])

    # ------------------------------------------------------------------
    # Node queries
    # ------------------------------------------------------------------

    @_observed_service_call(
        "service_node",
        metadata_fn=lambda self, identifier: {"identifier_len": len(identifier or "")},
    )
    def node(self, identifier: str) -> dict | None:
        """Return structured data for a file path or qualified symbol name.

        Parameters
        ----------
        identifier:
            Either a relative file path (``"src/services/auth.py"``) or a
            qualified symbol name (``"validate_credentials"`` or
            ``"AuthService.validate_credentials"``).

        Returns
        -------
        dict with callers, callees, parameters, community, and pathway membership.
        Returns None if not found.
        """
        store = self._get_store()

        # Try as file first
        file_data = store.get_file(identifier)
        if file_data:
            return {
                "type": "file",
                **file_data,
                "functions": store.get_functions_in_file(identifier),
                "classes": store.get_classes_in_file(identifier),
            }

        # Try as function (by name search)
        matches = store.search_functions_by_name(identifier, limit=5)
        if len(matches) == 1:
            fn_id = matches[0]["id"]
            fn = store.get_function_by_id(fn_id)
            if fn:
                return {
                    "type": "function",
                    **fn,
                    "callers": store.get_callers(fn_id),
                    "callees": store.get_callees(fn_id),
                }
        if len(matches) > 1:
            return {"type": "ambiguous", "matches": matches}

        return None

    @_observed_service_call("service_get_all_files")
    def get_all_files(self) -> list[dict]:
        """Return all indexed files with their metadata.

        Returns
        -------
        list of dicts: id, path, language, line_count, source_hash,
        is_test, is_config — sorted by path.
        """
        return self._get_store().get_all_files()

    # ------------------------------------------------------------------
    # Entry points & dead code
    # ------------------------------------------------------------------

    @_observed_service_call(
        "service_entry_points",
        metadata_fn=lambda self, limit=20: {"limit": int(limit)},
    )
    def entry_points(self, limit: int = 20) -> list[dict]:
        """Return the top entry points scored by the pathway scorer.

        These are the functions most likely to be user-facing: HTTP route
        handlers, CLI commands, event handlers, bot tick loops, etc.

        Returns
        -------
        list of dicts: qualified_name, file_path, entry_score, signature.
        """
        return self._get_store().get_entry_points(limit=limit)

    @_observed_service_call(
        "service_dead_code",
        metadata_fn=lambda self, min_tier="probably_dead": {"min_tier": min_tier},
    )
    def dead_code(self, min_tier: str = "probably_dead") -> list[dict]:
        """Return symbols detected as unreachable, filtered by confidence tier.

        Parameters
        ----------
        min_tier:
            Minimum confidence tier to include.  Options (highest → lowest):

            ``"definitely_dead"``
                Zero callers in any production or test code.  Highest
                confidence; very few false positives.
            ``"probably_dead"`` *(default)*
                Only called from test files, only via fuzzy edges, or a
                JS module-scope function whose global reachability cannot
                be determined statically.
            ``"possibly_dead"``
                Exported symbol with no callers at all — may be public API.

        Note
        ----
        JS/TS module-scope functions in files loaded via ``<script src>``
        are exempted entirely and will not appear at any tier.

        Returns
        -------
        list of dicts with keys: ``qualified_name``, ``file_path``,
        ``line_start``, ``dead_code_tier``, ``dead_code_reason``.
        """
        return self._get_store().get_dead_functions(min_tier=min_tier)

    @_observed_service_call(
        "service_duplicates",
        metadata_fn=lambda self, min_severity="medium": {"min_severity": min_severity},
    )
    def duplicates(self, min_severity: str = "medium") -> list[dict]:
        """Return groups of symbols that appear to be duplicated across files.

        Parameters
        ----------
        min_severity:
            Minimum severity to include.  Options (highest → lowest):

            ``"high"``
                Same qualified name in 2+ non-test files — almost certainly
                unintentional duplication or a superseded implementation.
            ``"medium"`` *(default)*
                Same name + identical parameter signature in 2+ non-test
                files — likely copy-pasted helpers.
            ``"low"``
                Same bare name repeated 3+ times in a single non-test file —
                usually copy-pasted test boilerplate that should be
                parameterised.

        Returns
        -------
        list of dicts with keys: ``name``, ``kind``, ``occurrence_count``,
        ``file_paths``, ``severity``, ``reason``, ``is_superseded``.
        """
        _SORDER = {"high": 0, "medium": 1, "low": 2}
        allowed = {s for s, r in _SORDER.items()
                   if r <= _SORDER.get(min_severity, 1)}
        all_groups = self._get_store().get_all_duplicate_symbols()
        return [g for g in all_groups if g.get("severity") in allowed]

    _DOC_WARN_SEV_RANK = {"high": 0, "medium": 1, "low": 2}

    @_observed_service_call(
        "service_doc_warnings",
        metadata_fn=lambda self, severity=None, min_severity=None: {
            "severity": severity or "",
            "min_severity": min_severity or "",
        },
    )
    def doc_warnings(
        self,
        severity: str | None = None,
        *,
        min_severity: str | None = None,
    ) -> list[dict]:
        """Return Markdown backtick cross-checks against the symbol graph.

        Phase 15 emits ``moved_reference`` (high) when a path hint disagrees
        with where the symbol lives.  When ``doc_symbols_flag_unknown`` is set
        in ``repograph.index.yaml``, qualified tokens missing from the index
        produce ``unknown_reference`` (medium).

        Parameters
        ----------
        severity
            Deprecated alias for ``min_severity`` (same accepted values).
        min_severity
            Include warnings at least as severe as this level: ``high`` (only
            high-severity rows), ``medium`` (high + medium), ``low`` (all).
            Default is ``high``.

        Returns
        -------
        list of dicts with keys: ``doc_path``, ``line_number``,
        ``symbol_text``, ``warning_type``, ``severity``, ``context_snippet``.
        """
        m = min_severity if min_severity is not None else (severity if severity is not None else "high")
        cap = self._DOC_WARN_SEV_RANK.get(m, 0)
        rows = self._get_store().get_all_doc_warnings(severity=None)
        return [
            w for w in rows
            if self._DOC_WARN_SEV_RANK.get(w.get("severity"), 99) <= cap
        ]

    # ------------------------------------------------------------------
    # Impact / blast radius
    # ------------------------------------------------------------------

    @_observed_service_call(
        "service_impact",
        metadata_fn=lambda self, symbol, depth=3: {
            "symbol_len": len(symbol or ""),
            "depth": int(depth),
        },
    )
    def impact(self, symbol: str, depth: int = 3) -> dict:
        """Return **static** call-graph neighbours for a symbol (approximate blast radius).

        Results reflect **persisted** ``CALLS`` edges only: dynamic dispatch,
        ``getattr``, plugins, and unresolved name collisions may omit real callers
        or callees. Cross-check important renames with search and tests.

        Parameters
        ----------
        symbol:
            Qualified function or method name.
        depth:
            How many hops of the call graph to traverse.

        Returns
        -------
        dict with keys:
            - ``direct_callers``: functions that call this symbol directly
            - ``transitive_callers``: functions that reach this symbol
              within ``depth`` hops
            - ``files_affected``: sorted file paths containing callers
            - ``warnings``: heuristic tags (see ``repograph.diagnostics.impact_warnings``)
        """
        from repograph.diagnostics.impact_warnings import build_impact_warnings

        store = self._get_store()
        matches = store.search_functions_by_name(symbol, limit=5)
        if not matches:
            return {
                "error": f"Symbol not found: {symbol}",
                "direct_callers": [],
                "transitive_callers": [],
                "files_affected": [],
                "warnings": ["symbol_not_found"],
            }
        if len(matches) > 1:
            return {
                "ambiguous": True,
                "matches": [m["qualified_name"] for m in matches],
                "warnings": build_impact_warnings(
                    direct_callers=[], has_duplicate_name_matches=True,
                ),
            }

        fn_id = matches[0]["id"]
        direct = store.get_callers(fn_id)
        via_interface = False

        # If no direct callers found, check whether this is a concrete method
        # that implements an interface — callers may reference the interface type
        # rather than the concrete class.  This is common with ABCs and protocols.
        if not direct:
            interface_callers = store.get_interface_callers(fn_id)
            if interface_callers:
                direct = interface_callers
                via_interface = True

        seen: set[str] = {fn_id} | {c["id"] for c in direct}
        frontier = list(seen - {fn_id})
        transitive: list[dict] = list(direct)

        for _ in range(depth - 1):
            next_frontier: list[str] = []
            for fid in frontier:
                for caller in store.get_callers(fid):
                    if caller["id"] not in seen:
                        seen.add(caller["id"])
                        transitive.append(caller)
                        next_frontier.append(caller["id"])
            frontier = next_frontier
            if not frontier:
                break

        files_affected = sorted({c["file_path"] for c in transitive})
        warnings = build_impact_warnings(direct_callers=direct)
        if via_interface:
            warnings.append("callers_resolved_via_interface")
        return {
            "symbol": matches[0]["qualified_name"],
            "file": matches[0]["file_path"],
            "direct_callers": direct,
            "transitive_callers": transitive,
            "files_affected": files_affected,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    @_observed_service_call(
        "service_search",
        metadata_fn=lambda self, query, limit=10: {
            "query_len": len(query or ""),
            "limit": int(limit),
        },
    )
    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search for symbols by name (fuzzy substring match).

        Parameters
        ----------
        query:
            Keyword or partial name to search for.
        limit:
            Maximum results to return.

        Returns
        -------
        list of dicts: qualified_name, file_path, signature.
        """
        from repograph.search.query_tokens import tokenize_search_query

        store = self._get_store()
        terms = tokenize_search_query(query)
        if not terms:
            return []
        if len(terms) == 1:
            return store.search_functions_by_name(terms[0], limit=limit)
        seen: set[str] = set()
        merged: list[dict] = []
        for t in terms:
            for row in store.search_functions_by_name(t, limit=limit):
                rid = row["id"]
                if rid in seen:
                    continue
                seen.add(rid)
                merged.append(row)
                if len(merged) >= limit:
                    return merged
        return merged

    # ------------------------------------------------------------------
    # Module index
    # ------------------------------------------------------------------

    @_observed_service_call("service_modules")
    def modules(self) -> list[dict]:
        """Return the per-directory module index built by Phase 16.

        Each entry summarises one top-level directory: production vs test file
        counts, function counts (prod scope in ``function_count``, tests in
        ``test_function_count``), key classes, one-line summary, dead-code and
        duplicate counts.  This is the fastest way for an AI to build a mental
        map of a large repository without calling ``node()`` on every file.

        Returns
        -------
        list of dicts — sorted by path:
            path, display, depth, parent, category,
            prod_file_count, test_file_count, total_file_count,
            file_count (alias of prod_file_count),
            function_count, test_function_count, class_count,
            key_classes, summary, has_tests,
            dead_code_count, duplicate_count.
        Returns an empty list when the index has not been built yet
        (run ``sync()`` first).
        """
        import json as _json
        meta_path = os.path.join(self.repograph_dir, "meta", "modules.json")
        if not os.path.exists(meta_path):
            return []
        try:
            with open(meta_path, encoding="utf-8") as f:
                return _json.load(f)
        except Exception:
            return []

    @_observed_service_call(
        "service_config_registry",
        metadata_fn=lambda self, key=None: {"has_key_filter": key is not None},
    )
    def config_registry(self, key: str | None = None) -> dict:
        """Return the global config-key → consumer mapping built by Phase 17.

        Shows which pathways and source files read each configuration key.
        Use this to understand the blast radius of renaming or removing a
        config value.

        Parameters
        ----------
        key:
            When provided, return only the entry for that specific key.
            When None (default), return the full registry sorted by usage count.

        Returns
        -------
        dict mapping key names to ``{pathways, files, usage_count}`` dicts.
        Returns an empty dict when the registry has not been built yet.
        """
        import json as _json
        meta_path = os.path.join(self.repograph_dir, "meta", "config_registry.json")
        if not os.path.exists(meta_path):
            return {}
        try:
            with open(meta_path, encoding="utf-8") as f:
                registry = _json.load(f)
            if key is not None:
                return {key: registry[key]} if key in registry else {}
            return registry
        except Exception:
            return {}

    @_observed_service_call("service_config_registry_diagnostics")
    def config_registry_diagnostics(self) -> dict:
        """Return exporter diagnostics for config_registry generation."""
        import json as _json

        meta_path = os.path.join(self.repograph_dir, "meta", "config_registry_diagnostics.json")
        if not os.path.exists(meta_path):
            return {}
        try:
            with open(meta_path, encoding="utf-8") as f:
                payload = _json.load(f)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    @_observed_service_call("service_test_coverage")
    def test_coverage(self) -> list[dict]:
        """Return per-file *entry-point test reachability* (not line coverage).

        The exact semantics match ``ENTRY_POINT_TEST_COVERAGE_DEFINITION`` in
        ``repograph.graph_store.store_queries_analytics``.  Rows are sorted by
        ``coverage_pct`` ascending.

        Returns
        -------
        list of dicts:
            file_path, entry_point_count, tested_entry_points,
            coverage_pct (0–100), test_files (list of test file paths).
        """
        return self._get_store().get_test_coverage_map()

    @_observed_service_call("service_test_coverage_any_call")
    def test_coverage_any_call(self) -> list[dict]:
        """Per-file share of non-test functions with a test caller (any CALLS edge).

        Rows match ``ANY_CALL_TEST_COVERAGE_DEFINITION`` in
        ``store_queries_analytics``: ``file_path``, ``function_count``,
        ``tested_functions``, ``coverage_pct``, ``test_files``.
        """
        return self._get_store().get_any_call_test_coverage_map()

    @property
    def coverage_definition(self) -> str:
        """Short explanation of what ``test_coverage()`` measures."""
        return ENTRY_POINT_TEST_COVERAGE_DEFINITION

    @property
    def coverage_definition_any_call(self) -> str:
        """Short explanation of :meth:`test_coverage_any_call`."""
        return ANY_CALL_TEST_COVERAGE_DEFINITION

    @_observed_service_call(
        "service_invariants",
        metadata_fn=lambda self, inv_type=None, file_path=None: {
            "has_inv_type_filter": inv_type is not None,
            "has_file_filter": file_path is not None,
        },
    )
    def invariants(
        self,
        inv_type: str | None = None,
        file_path: str | None = None,
    ) -> list[dict]:
        """Return documented architectural invariants extracted by Phase 18.

        These are constraints, guarantees, and thread-safety notes explicitly
        written in docstrings (``INV-``, ``NEVER``, ``MUST NOT``, etc.).
        Surfacing them helps AI agents avoid accidentally violating them.

        Parameters
        ----------
        inv_type:
            Filter by invariant type: ``"constraint"``, ``"guarantee"``,
            ``"thread"``, or ``"lifecycle"``.  None returns all types.
        file_path:
            Filter to invariants on symbols defined in this file path.

        Returns
        -------
        list of dicts: symbol_name, symbol_type, file_path,
        invariant_text, invariant_type.
        """
        import json as _json
        meta_path = os.path.join(self.repograph_dir, "meta", "invariants.json")
        if not os.path.exists(meta_path):
            return []
        try:
            with open(meta_path, encoding="utf-8") as f:
                items = _json.load(f)
            if inv_type:
                items = [i for i in items if i.get("invariant_type") == inv_type]
            if file_path:
                items = [i for i in items if i.get("file_path") == file_path]
            return items
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Event topology, async tasks, interface map, constructor deps
    # ------------------------------------------------------------------

    @_observed_service_call("service_event_topology")
    def event_topology(self) -> list[dict]:
        """Return heuristic event-bus call sites (Phase 19 JSON)."""
        return self._get_store().get_event_topology()

    @_observed_service_call("service_async_tasks")
    def async_tasks(self) -> list[dict]:
        """Return asyncio task spawn records (Phase 20 JSON)."""
        return self._get_store().get_async_tasks()

    @_observed_service_call("service_interface_map")
    def interface_map(self) -> list[dict]:
        """Return inheritance-based interface → implementations map."""
        from repograph.plugins.static_analyzers.interface_map.plugin import get_interface_map

        return get_interface_map(self._get_store())

    @_observed_service_call(
        "service_constructor_deps",
        metadata_fn=lambda self, class_name, depth=2: {
            "class_name_len": len(class_name or ""),
            "depth": int(depth),
        },
    )
    def constructor_deps(self, class_name: str, depth: int = 2) -> dict:
        """Return ``__init__`` parameter names for a class."""
        return self._get_store().get_constructor_deps(class_name, depth=depth)

    @_observed_service_call("service_communities")
    def communities(self) -> list[dict]:
        """Return all detected communities (module clusters).

        Returns
        -------
        list of dicts: label, member_count, cohesion — sorted by member_count desc.
        """
        store = self._get_store()
        rows = store.query(
            "MATCH (c:Community) RETURN c.id, c.label, c.member_count, c.cohesion "
            "ORDER BY c.member_count DESC"
        )
        return [
            {"id": r[0], "label": r[1], "member_count": r[2], "cohesion": r[3]}
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Raw Cypher
    # ------------------------------------------------------------------

    @_observed_service_call(
        "service_query",
        metadata_fn=lambda self, cypher, params=None: {
            "cypher_len": len(cypher or ""),
            "param_count": len(params or {}),
        },
    )
    def query(self, cypher: str, params: dict | None = None) -> list[list]:
        """Execute a raw Cypher query against the graph database.

        Parameters
        ----------
        cypher:
            KuzuDB Cypher query string.
        params:
            Optional parameter dict for the query.

        Returns
        -------
        list of rows, each row is a list of values.
        """
        return self._get_store().query(cypher, params)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_initialized(self) -> bool:
        db = os.path.join(self.repograph_dir, "graph.db")
        wal = os.path.join(self.repograph_dir, "graph.db.wal")
        return os.path.exists(db) or os.path.exists(wal)

    def _get_store(self):
        if self._store is None:
            from repograph.graph_store.store import GraphStore
            db = os.path.join(self.repograph_dir, "graph.db")
            with self.span("service_open_store", db_path=db):
                self._store = GraphStore(db)
                self._store.prepare_read_state()
            self.logger.debug("service store opened", db_path=db)
        return self._store

    # ------------------------------------------------------------------
    # Full report — single call, all intelligence
    # ------------------------------------------------------------------

    @_observed_service_call(
        "service_full_report",
        metadata_fn=lambda self, max_pathways=10, max_dead=20: {
            "max_pathways": int(max_pathways),
            "max_dead": int(max_dead),
        },
    )
    def full_report(self, max_pathways: int = 10, max_dead: int = 20) -> dict:
        """Return every piece of intelligence the tool can provide in one call.

        This is the canonical "dump everything" method.  Both the
        ``repograph report`` CLI command and the interactive menu's full-report
        view delegate here so there is a single source of truth.

        Use this when you want a complete picture of a repo without making
        a separate API call for each data type.  The returned dict is large
        but fully self-contained — no follow-up queries needed for a full
        mental model.

        Parameters
        ----------
        max_pathways:
            Maximum number of pathways to include (sorted by importance desc).
        max_dead:
            Maximum number of dead-code symbols to include.

        Returns
        -------
        dict with the following keys:

        ``meta``
            repo_path, repograph_dir, initialized (bool)

        ``health``
            status, sync_mode, call_edges_total, generated_at, strict,
            contract_version (see ``repograph.trust.contract``)

        ``stats``
            files, functions, classes, variables, imports, pathways,
            communities, last_sync

        ``purpose``
            One-line repo description extracted from README.

        ``modules``
            Per-directory structural map (from ``modules()``).

        ``entry_points``
            Top 20 entry points with scores.

        ``pathways``
            Top N pathways (sorted by importance), each including the
            full context doc so the caller can read execution flows
            without additional queries.

        ``dead_code``
            ``definitely_dead`` and ``probably_dead`` symbols (up to
            ``max_dead`` each).

        ``duplicates``
            All high + medium severity duplicate groups, each with
            ``canonical_path`` and ``superseded_paths``.

        ``invariants``
            All documented architectural constraints.

        ``config_registry``
            Full config-key → consumer mapping (top 30 by usage).

        ``test_coverage``
            Per-file entry-point reachability from test code (all files,
            sorted by coverage ascending — least-tested first).

        ``coverage_definition``
            Same string as the ``coverage_definition`` property — documents the metric.

        ``doc_warnings``
            All high-severity doc-symbol cross-check warnings.

        ``communities``
            Top 20 communities by member count.

        ``runtime_observations``
            Count of functions with persisted runtime traces matching the current
            ``source_hash`` (see ``persist_runtime_overlay_to_store``).
        """
        from repograph.plugins.exporters.agent_guide.generator import _extract_repo_summary

        if not self._is_initialized():
            return {"meta": {"initialized": False, "repo_path": self.repo_path}}

        # ── Parallel-ish data gathering (sequential, shared store handle) ──
        status = self.status()
        health = status.get("health", {})
        stats = {k: v for k, v in status.items() if k not in ("health",)}

        purpose = ""
        try:
            purpose = _extract_repo_summary(self.repo_path)
        except Exception:
            pass

        # Entry points
        eps = self.entry_points(limit=20)

        # Pathways — include full context doc for each
        all_pathways = self.pathways(min_confidence=0.0, include_tests=False)
        top_pathways_meta = sorted(
            all_pathways,
            key=lambda p: (-(p.get("importance_score") or 0), -(p.get("confidence") or 0)),
        )[:max_pathways]
        pathways_total = len(all_pathways)

        store = self._get_store()
        top_pathways_full = []
        for pw in top_pathways_meta:
            full_pw = store.get_pathway(pw["name"]) or pw
            top_pathways_full.append(full_pw)

        # Dead code — two tiers, split production vs tooling/docs/tests
        all_def = self.dead_code(min_tier="definitely_dead")
        all_prob = [
            d for d in self.dead_code(min_tier="probably_dead")
            if d.get("dead_code_tier") == "probably_dead"
        ]
        definitely_dead = [d for d in all_def if not d.get("is_non_production")][:max_dead]
        probably_dead = [d for d in all_prob if not d.get("is_non_production")][:max_dead]
        definitely_dead_tooling = [d for d in all_def if d.get("is_non_production")][:max_dead]
        probably_dead_tooling = [d for d in all_prob if d.get("is_non_production")][:max_dead]

        # Duplicates
        dups = self.duplicates(min_severity="medium")

        # New Phase 2 data
        mods = self.modules()
        inv = self.invariants()
        cfg_reg = self.config_registry()
        cfg_diag = self.config_registry_diagnostics()
        # Trim to top 30 config keys by usage
        cfg_top = dict(list(cfg_reg.items())[:30])

        test_cov = self.test_coverage()
        test_cov_any = self.test_coverage_any_call()

        # Doc warnings
        doc_warns = self.doc_warnings(min_severity="medium")

        # Communities
        all_comms = self.communities()
        comms = all_comms[:20]
        communities_total = len(all_comms)

        # Runtime overlay rows persisted in graph (see persist_runtime_overlay_to_store)
        all_fn = store.get_all_functions()
        rt_valid = sum(
            1
            for f in all_fn
            if f.get("runtime_observed")
            and (f.get("runtime_observed_for_hash") or "") == (f.get("source_hash") or "")
        )

        report_warnings = _build_report_warnings(
            health=health,
            pathways_total=pathways_total,
            pathways_shown=len(top_pathways_full),
            communities_total=communities_total,
            communities_shown=len(comms),
            cfg_top=cfg_top,
            cfg_diag=cfg_diag,
        )

        return {
            "meta": {
                "repo_path": self.repo_path,
                "repograph_dir": self.repograph_dir,
                "initialized": True,
            },
            "health": health,
            "stats": stats,
            "count_semantics": {
                "functions": (
                    "Reported function counts exclude internal is_module_caller sentinel nodes."
                ),
                "pathways": (
                    "Default pathway/report views exclude auto_detected_test pathways unless include_tests=True."
                ),
            },
            "sync_semantics": {
                "dynamic_analysis": health.get("dynamic_analysis") or {},
                "coverage_metric": "entry_point_reachability_not_line_coverage",
            },
            "purpose": purpose,
            "modules": mods,
            "entry_points": eps,
            "pathways": top_pathways_full,
            "pathways_summary": {
                "total": pathways_total,
                "shown": len(top_pathways_full),
                "limit": max_pathways,
            },
            "runtime_observations": {
                "functions_with_valid_runtime_revision": rt_valid,
                "note": (
                    "Counts Function nodes where runtime traces matched the current source_hash. "
                    "Stale rows clear when the file is re-indexed."
                ),
            },
            "dead_code": {
                "definitely_dead": definitely_dead,
                "probably_dead": probably_dead,
                "definitely_dead_tooling": definitely_dead_tooling,
                "probably_dead_tooling": probably_dead_tooling,
            },
            "duplicates": dups,
            "invariants": inv,
            "config_registry": cfg_top,
            "config_registry_diagnostics": cfg_diag,
            "test_coverage": test_cov,
            "coverage_definition": ENTRY_POINT_TEST_COVERAGE_DEFINITION,
            "test_coverage_any_call": test_cov_any,
            "coverage_definition_any_call": ANY_CALL_TEST_COVERAGE_DEFINITION,
            "doc_warnings": doc_warns,
            "communities": comms,
            "communities_summary": {
                "total": communities_total,
                "shown": len(comms),
                "limit": 20,
            },
            "report_warnings": report_warnings,
        }

    @_observed_service_call(
        "service_pathway_document",
        metadata_fn=lambda self, name: {"pathway_name": name},
    )
    def pathway_document(self, name: str) -> str | None:
        """Return the full context document for a pathway, generating it on demand."""
        store = self._get_store()
        pathway = store.get_pathway(name)
        if pathway is None:
            return None
        ctx = pathway.get("context_doc") or ""
        if not ctx:
            from repograph.plugins.exporters.pathway_contexts.generator import generate_pathway_context
            ctx = generate_pathway_context(pathway["id"], store)
        return ctx or None

    @_observed_service_call(
        "service_dependents",
        metadata_fn=lambda self, symbol, depth=3: {
            "symbol_len": len(symbol or ""),
            "depth": int(depth),
        },
    )
    def dependents(self, symbol: str, depth: int = 3) -> dict:
        """Return direct/transitive callers grouped by depth."""
        store = self._get_store()
        results = store.search_functions_by_name(symbol, limit=1)
        if not results:
            return {"error": f"Symbol '{symbol}' not found"}
        fn_id = results[0]["id"]
        levels: dict[int, list[dict]] = {}
        visited: set[str] = {fn_id}
        queue = [(fn_id, 0)]
        while queue:
            cur_id, cur_depth = queue.pop(0)
            if cur_depth >= depth:
                continue
            callers = store.get_callers(cur_id)
            for c in callers:
                if c["id"] not in visited:
                    visited.add(c["id"])
                    levels.setdefault(cur_depth + 1, []).append(c)
                    queue.append((c["id"], cur_depth + 1))
        return {"symbol": symbol, "dependents_by_depth": levels}

    @_observed_service_call(
        "service_dependencies",
        metadata_fn=lambda self, symbol, depth=3: {
            "symbol_len": len(symbol or ""),
            "depth": int(depth),
        },
    )
    def dependencies(self, symbol: str, depth: int = 3) -> dict:
        """Return transitive callees grouped by depth."""
        store = self._get_store()
        results = store.search_functions_by_name(symbol, limit=1)
        if not results:
            return {"error": f"Symbol '{symbol}' not found"}
        fn_id = results[0]["id"]
        levels: dict[int, list[dict]] = {}
        visited: set[str] = {fn_id}
        queue = [(fn_id, 0)]
        while queue:
            cur_id, cur_depth = queue.pop(0)
            if cur_depth >= depth:
                continue
            callees = store.get_callees(cur_id)
            for c in callees:
                if c["id"] not in visited:
                    visited.add(c["id"])
                    levels.setdefault(cur_depth + 1, []).append(c)
                    queue.append((c["id"], cur_depth + 1))
        return {"symbol": symbol, "dependencies_by_depth": levels}

    @_observed_service_call(
        "service_trace_variable",
        metadata_fn=lambda self, variable_name: {"variable_name_len": len(variable_name or "")},
    )
    def trace_variable(self, variable_name: str) -> dict:
        """Trace occurrences and FLOWS_INTO edges for a variable name."""
        store = self._get_store()
        rows = store.query(
            """
            MATCH (v:Variable {name: $name})
            RETURN v.id, v.function_id, v.file_path, v.line_number,
                   v.inferred_type, v.is_parameter, v.is_return
            LIMIT 20
            """,
            {"name": variable_name},
        )
        if not rows:
            return {"error": f"Variable '{variable_name}' not found"}
        occurrences = [
            {
                "variable_id": r[0],
                "function_id": r[1],
                "file_path": r[2],
                "line_number": r[3],
                "inferred_type": r[4],
                "is_parameter": r[5],
                "is_return": r[6],
            }
            for r in rows
        ]
        var_ids = {o["variable_id"] for o in occurrences}
        flows = store.get_flows_into_edges()
        relevant_flows = [e for e in flows if e["from"] in var_ids or e["to"] in var_ids]
        return {"variable_name": variable_name, "occurrences": occurrences, "flows": relevant_flows}


    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Explicitly close the database connection."""
        if self._store is not None:
            with self.span("service_close_store"):
                self._store.close()
                self._store = None
        self._shutdown_owned_observability_session()

    # ------------------------------------------------------------------
    # Observability log access
    # ------------------------------------------------------------------

    def _log_dir(self) -> Path:
        return Path(self.repograph_dir) / "logs"

    @_observed_service_call("service_list_log_sessions")
    def list_log_sessions(self) -> list[dict]:
        """List available log sessions with run_id, timestamp, and record counts.

        Returns a list of dicts sorted most-recent-first, each with:
        ``run_id``, ``timestamp_iso``, ``record_count``, ``error_count``.
        """
        import json, time as _time
        log_dir = self._log_dir()
        if not log_dir.exists():
            return []
        sessions = []
        for run_dir in sorted(log_dir.iterdir(), key=lambda d: d.stat().st_mtime, reverse=True):
            if not run_dir.is_dir():
                continue
            all_j = run_dir / "all.jsonl"
            err_j = run_dir / "errors.jsonl"
            n_all = sum(1 for _ in all_j.open() if _.strip()) if all_j.exists() else 0
            n_err = sum(1 for _ in err_j.open() if _.strip()) if err_j.exists() else 0
            sessions.append({
                "run_id": run_dir.name,
                "timestamp_iso": _time.strftime(
                    "%Y-%m-%dT%H:%M:%S", _time.localtime(run_dir.stat().st_mtime)
                ),
                "record_count": n_all,
                "error_count": n_err,
            })
        return sessions

    @_observed_service_call(
        "service_get_log_session",
        metadata_fn=lambda self, run_id=None, subsystem=None, limit=500: {
            "has_run_id": run_id is not None,
            "subsystem": subsystem or "",
            "limit": int(limit),
        },
    )
    def get_log_session(
        self,
        run_id: str | None = None,
        subsystem: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        """Return parsed log records for a session, optionally filtered by subsystem.

        Args:
            run_id:    Run ID to fetch (default: most recent).
            subsystem: If set, read the ``<subsystem>.jsonl`` file instead of ``all.jsonl``.
            limit:     Maximum number of records to return (most recent).
        """
        import json
        log_dir = self._log_dir()
        run_dir = self._resolve_run_dir(log_dir, run_id)
        if run_dir is None:
            return []
        filename = f"{subsystem}.jsonl" if subsystem else "all.jsonl"
        log_file = run_dir / filename
        if not log_file.exists():
            return []
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        records = []
        for line in lines:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return records[-limit:]

    @_observed_service_call(
        "service_get_recent_errors",
        metadata_fn=lambda self, run_id=None, limit=50: {
            "has_run_id": run_id is not None,
            "limit": int(limit),
        },
    )
    def get_recent_errors(self, run_id: str | None = None, limit: int = 50) -> list[dict]:
        """Return the most recent ERROR and CRITICAL records."""
        import json
        log_dir = self._log_dir()
        run_dir = self._resolve_run_dir(log_dir, run_id)
        if run_dir is None:
            return []
        err_file = run_dir / "errors.jsonl"
        if not err_file.exists():
            return []
        lines = err_file.read_text(encoding="utf-8", errors="replace").splitlines()
        records = []
        for line in lines:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return records[-limit:]

    # ── I1: Change impact analysis ────────────────────────────────────────────

    def compute_diff_impact(
        self,
        changed_paths: list[str],
        max_hops: int = 5,
    ) -> list[dict]:
        """Return a ranked list of functions impacted by the given changed files.

        Each entry is a dict with keys: ``fn_id``, ``qualified_name``,
        ``file_path``, ``hop``, ``impact_score``, ``via_http``, ``edge_path``.

        Parameters
        ----------
        changed_paths:
            Repo-relative file paths that changed.
        max_hops:
            Maximum call-graph traversal depth.
        """
        from repograph.services.impact_analysis import compute_impact, ImpactedFunction

        results: list[ImpactedFunction] = compute_impact(
            self._get_store(), changed_paths=changed_paths, max_hops=max_hops,
        )
        return [
            {
                "fn_id": r.fn_id,
                "qualified_name": r.qualified_name,
                "file_path": r.file_path,
                "hop": r.hop,
                "impact_score": r.impact_score,
                "via_http": r.via_http,
                "edge_path": r.edge_path,
            }
            for r in results
        ]

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

    # Context manager support
    def __enter__(self) -> "RepoGraphService":
        self._ensure_observability_session()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"RepoGraphService(repo={self.repo_path!r})"
