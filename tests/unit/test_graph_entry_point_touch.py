"""Direct calls into production entry points to improve *graph* test reachability.

``repograph test-map`` counts Phase-10 ``is_entry_point`` functions that have a
``CALLS`` edge from ``is_test`` code.  These tests call ``build_plugin`` (and
the pipeline no-op builder) for **every** built-in plugin module so the index
reflects test→production reachability.

This is complementary to line coverage (``pytest --cov``).

For ``test-map`` reachability into each ``plugin.py``, see
``test_plugin_build_direct_per_module.py`` — one test per module with a direct
``build_plugin`` call; dynamic :func:`import_build_plugin` often does not
resolve per-file edges.
"""
from __future__ import annotations

import traceback

import pytest

from repograph.core.evidence.taxonomy import CAP_SYMBOLS, SOURCE_STATIC, evidence_tag
from repograph.core.evidence.policy import annotate_finding, policy_for, summarize_findings
from repograph.diagnostics.env_doctor import collect_doctor_results
from repograph.graph_store.kuzu_loader import load_kuzu
from repograph.interactive.cli_catalog import CliCategory, all_categories
from repograph.interactive.graph_queries import (
    dependencies_by_depth,
    dependents_by_depth,
    hybrid_search,
    repograph_cli_path,
    trace_variable,
)
from repograph.pipeline.health import read_health_json
from repograph.pipeline.sync_state import lock_status
from repograph.plugins.discovery import (
    DEMAND_ANALYZER_ORDER,
    DYNAMIC_ANALYZER_ORDER,
    EVIDENCE_PRODUCER_ORDER,
    EXPORTER_ORDER,
    FRAMEWORK_ADAPTER_ORDER,
    PARSER_ORDER,
    STATIC_ANALYZER_ORDER,
    import_build_plugin,
    iter_build_plugins,
    load_optional_entry_point_plugins,
)
from repograph.quality.integrity import run_sync_invariants


def _standard_build_plugin_jobs() -> list[tuple[str, str]]:
    """Every ``<base_pkg>.<name>.plugin:build_plugin`` discovered via ``discovery.py`` orders.

    ``coverage_tracer`` lives under ``dynamic_analyzers/`` but is registered as a
    **tracer** — it is not listed in ``DYNAMIC_ANALYZER_ORDER``, so it is appended.
    """
    rows: list[tuple[str, str]] = []
    for base_pkg, names in (
        ("repograph.plugins.parsers", PARSER_ORDER),
        ("repograph.plugins.framework_adapters", FRAMEWORK_ADAPTER_ORDER),
        ("repograph.plugins.static_analyzers", STATIC_ANALYZER_ORDER),
        ("repograph.plugins.demand_analyzers", DEMAND_ANALYZER_ORDER),
        ("repograph.plugins.exporters", EXPORTER_ORDER),
        ("repograph.plugins.evidence_producers", EVIDENCE_PRODUCER_ORDER),
        ("repograph.plugins.dynamic_analyzers", DYNAMIC_ANALYZER_ORDER),
    ):
        for name in names:
            rows.append((base_pkg, name))
    rows.append(("repograph.plugins.dynamic_analyzers", "coverage_tracer"))
    return rows


def _instantiate_build_plugin(base_pkg: str, name: str) -> str | None:
    """Return an error string, or None on success."""
    label = f"{base_pkg}.{name}.plugin:build_plugin"
    try:
        build = import_build_plugin(base_pkg, name)
        plugin = build()
        pid = getattr(plugin, "plugin_id", None)
        if callable(pid):
            _ = pid()
        elif hasattr(plugin, "phase_id"):
            _ = getattr(plugin, "phase_id")
        else:
            return f"{label}: instance has no plugin_id() or phase_id"
    except Exception:
        return f"{label}:\n{traceback.format_exc()}"
    return None


def _instantiate_pipeline_phase_no_op() -> str | None:
    label = "repograph.plugins.pipeline_phases.no_op.plugin:build_no_op"
    try:
        from repograph.plugins.pipeline_phases.no_op.plugin import build_no_op

        phase = build_no_op()
        if getattr(phase, "phase_id", None) != "phase.experimental_no_op":
            return f"{label}: unexpected phase_id"
    except Exception:
        return f"{label}:\n{traceback.format_exc()}"
    return None


def test_every_builtin_build_plugin_family_member_gracefully() -> None:
    """Import and instantiate **each** built-in ``build_plugin``; report all failures once."""
    failures: list[str] = []
    for base_pkg, name in _standard_build_plugin_jobs():
        err = _instantiate_build_plugin(base_pkg, name)
        if err:
            failures.append(err)
    err_noop = _instantiate_pipeline_phase_no_op()
    if err_noop:
        failures.append(err_noop)
    assert not failures, "build_plugin failures:\n\n" + "\n---\n".join(failures)


def test_discovery_iter_build_plugins_and_optional_eps() -> None:
    fns = iter_build_plugins("repograph.plugins.parsers", ("python",), skip_import_error=True)
    assert len(fns) == 1
    registered: list[object] = []

    def _reg(p: object) -> None:
        registered.append(p)

    load_optional_entry_point_plugins("nonexistent.group.xyz", _reg)


def test_evidence_policy_and_taxonomy() -> None:
    pol = policy_for("high")
    assert pol.action
    ann = annotate_finding({"severity": "medium", "kind": "ui_to_db_shortcut"}, family="boundary_shortcuts")
    assert "policy" in ann
    summary = summarize_findings([ann])
    assert summary.get("total", 0) >= 1
    tag = evidence_tag(CAP_SYMBOLS, SOURCE_STATIC)
    assert tag.as_dict()["source"] == SOURCE_STATIC


@pytest.mark.slow
def test_env_doctor_collect(tmp_path) -> None:
    """Runs subprocess probes (isolated import); keep behind ``-m slow`` for fast PR runs."""
    results = collect_doctor_results(repo_path=str(tmp_path), verbose=False)
    assert any(r.name == "python" for r in results)


def test_pipeline_health_and_lock_helpers(tmp_path) -> None:
    assert read_health_json(str(tmp_path / ".repograph")) is None
    status, _info = lock_status(str(tmp_path / ".repograph"))
    assert status in ("none", "stale", "active")


def test_kuzu_loader() -> None:
    mod = load_kuzu()
    assert mod is not None


def test_interactive_graph_queries(simple_store) -> None:
    hybrid_search(simple_store, "run", limit=3)
    trace_variable(simple_store, "nonexistent_var_xyz")
    dependents_by_depth(simple_store, "run", depth=2)
    dependencies_by_depth(simple_store, "run", depth=2)
    p = repograph_cli_path()
    assert isinstance(p, str) and len(p) > 0


def test_cli_catalog_all_categories_structure() -> None:
    cats = all_categories()
    assert len(cats) >= 1
    assert isinstance(cats[0], CliCategory)


def test_cli_browser_print_entry(capsys: pytest.CaptureFixture[str]) -> None:
    from repograph.interactive.cli_browser import _print_entry

    entry = all_categories()[0].commands[0]
    _print_entry(entry)
    out = capsys.readouterr().out
    assert entry.title in out or entry.key in out


def test_quality_run_sync_invariants(simple_store) -> None:
    result = run_sync_invariants(simple_store)
    assert result.ok, [v.message for v in result.violations]
