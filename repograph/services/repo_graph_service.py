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

import os
from typing import Any

from repograph.graph_store.store_queries_analytics import (
    ANY_CALL_TEST_COVERAGE_DEFINITION,
    ENTRY_POINT_TEST_COVERAGE_DEFINITION,
)
from repograph.core.evidence import summarize_findings


class RepoGraphService:
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

    # ------------------------------------------------------------------
    # Core pipeline
    # ------------------------------------------------------------------

    def sync(
        self,
        full: bool = False,
        include_embeddings: bool = False,
        max_context_tokens: int = 2000,
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

    def entry_points(self, limit: int = 20) -> list[dict]:
        """Return the top entry points scored by the pathway scorer.

        These are the functions most likely to be user-facing: HTTP route
        handlers, CLI commands, event handlers, bot tick loops, etc.

        Returns
        -------
        list of dicts: qualified_name, file_path, entry_score, signature.
        """
        return self._get_store().get_entry_points(limit=limit)

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

    def event_topology(self) -> list[dict]:
        """Return heuristic event-bus call sites (Phase 19 JSON)."""
        return self._get_store().get_event_topology()

    def async_tasks(self) -> list[dict]:
        """Return asyncio task spawn records (Phase 20 JSON)."""
        return self._get_store().get_async_tasks()

    def interface_map(self) -> list[dict]:
        """Return inheritance-based interface → implementations map."""
        from repograph.plugins.static_analyzers.interface_map.plugin import get_interface_map

        return get_interface_map(self._get_store())

    def constructor_deps(self, class_name: str, depth: int = 2) -> dict:
        """Return ``__init__`` parameter names for a class."""
        return self._get_store().get_constructor_deps(class_name, depth=depth)

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
            self._store = GraphStore(db)
            self._store.initialize_schema()
        return self._store

    # ------------------------------------------------------------------
    # Full report — single call, all intelligence
    # ------------------------------------------------------------------

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
        # Trim to top 30 config keys by usage
        cfg_top = dict(list(cfg_reg.items())[:30])

        test_cov = self.test_coverage()
        test_cov_any = self.test_coverage_any_call()

        # Doc warnings
        doc_warns = self.doc_warnings(min_severity="medium")

        # Communities
        comms = self.communities()[:20]

        # Runtime overlay rows persisted in graph (see persist_runtime_overlay_to_store)
        all_fn = store.get_all_functions()
        rt_valid = sum(
            1
            for f in all_fn
            if f.get("runtime_observed")
            and (f.get("runtime_observed_for_hash") or "") == (f.get("source_hash") or "")
        )

        return {
            "meta": {
                "repo_path": self.repo_path,
                "repograph_dir": self.repograph_dir,
                "initialized": True,
            },
            "health": health,
            "stats": stats,
            "purpose": purpose,
            "modules": mods,
            "entry_points": eps,
            "pathways": top_pathways_full,
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
            "test_coverage": test_cov,
            "coverage_definition": ENTRY_POINT_TEST_COVERAGE_DEFINITION,
            "test_coverage_any_call": test_cov_any,
            "coverage_definition_any_call": ANY_CALL_TEST_COVERAGE_DEFINITION,
            "doc_warnings": doc_warns,
            "communities": comms,
        }

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
            self._store.close()
            self._store = None

    # Context manager support
    def __enter__(self) -> "RepoGraphService":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"RepoGraphService(repo={self.repo_path!r})"
