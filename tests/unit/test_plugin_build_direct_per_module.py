"""One test per plugin module: direct ``from … import build_plugin`` + call.

Maximizes static ``CALLS`` edges for ``repograph test-map`` (one test function →
one ``build_plugin`` callee per module).  Sync with
``repograph.plugins.discovery`` order tuples; ``coverage_tracer`` is not in
``DYNAMIC_ANALYZER_ORDER``; ``pipeline_phases.no_op`` uses ``build_no_op``.
"""
from __future__ import annotations


# --- parsers ---


def test_parsers_python_build_plugin_direct() -> None:
    from repograph.plugins.parsers.python.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_parsers_javascript_build_plugin_direct() -> None:
    from repograph.plugins.parsers.javascript.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_parsers_typescript_build_plugin_direct() -> None:
    from repograph.plugins.parsers.typescript.plugin import build_plugin

    assert build_plugin().plugin_id()


# --- static analyzers ---


def test_static_analyzers_pathways_build_plugin_direct() -> None:
    from repograph.plugins.static_analyzers.pathways.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_static_analyzers_dead_code_build_plugin_direct() -> None:
    from repograph.plugins.static_analyzers.dead_code.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_static_analyzers_duplicates_build_plugin_direct() -> None:
    from repograph.plugins.static_analyzers.duplicates.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_static_analyzers_event_topology_build_plugin_direct() -> None:
    from repograph.plugins.static_analyzers.event_topology.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_static_analyzers_async_tasks_build_plugin_direct() -> None:
    from repograph.plugins.static_analyzers.async_tasks.plugin import build_plugin

    assert build_plugin().plugin_id()


# --- framework adapters ---


def test_framework_adapters_flask_build_plugin_direct() -> None:
    from repograph.plugins.framework_adapters.flask.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_framework_adapters_fastapi_build_plugin_direct() -> None:
    from repograph.plugins.framework_adapters.fastapi.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_framework_adapters_react_build_plugin_direct() -> None:
    from repograph.plugins.framework_adapters.react.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_framework_adapters_nextjs_build_plugin_direct() -> None:
    from repograph.plugins.framework_adapters.nextjs.plugin import build_plugin

    assert build_plugin().plugin_id()


# --- demand analyzers ---


def test_demand_analyzers_dead_code_build_plugin_direct() -> None:
    from repograph.plugins.demand_analyzers.dead_code.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_demand_analyzers_private_surface_access_build_plugin_direct() -> None:
    from repograph.plugins.demand_analyzers.private_surface_access.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_demand_analyzers_config_boundary_reads_build_plugin_direct() -> None:
    from repograph.plugins.demand_analyzers.config_boundary_reads.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_demand_analyzers_db_shortcuts_build_plugin_direct() -> None:
    from repograph.plugins.demand_analyzers.db_shortcuts.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_demand_analyzers_ui_boundary_paths_build_plugin_direct() -> None:
    from repograph.plugins.demand_analyzers.ui_boundary_paths.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_demand_analyzers_duplicates_build_plugin_direct() -> None:
    from repograph.plugins.demand_analyzers.duplicates.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_demand_analyzers_contract_rules_build_plugin_direct() -> None:
    from repograph.plugins.demand_analyzers.contract_rules.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_demand_analyzers_boundary_shortcuts_build_plugin_direct() -> None:
    from repograph.plugins.demand_analyzers.boundary_shortcuts.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_demand_analyzers_architecture_conformance_build_plugin_direct() -> None:
    from repograph.plugins.demand_analyzers.architecture_conformance.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_demand_analyzers_boundary_rules_build_plugin_direct() -> None:
    from repograph.plugins.demand_analyzers.boundary_rules.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_demand_analyzers_class_roles_build_plugin_direct() -> None:
    from repograph.plugins.demand_analyzers.class_roles.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_demand_analyzers_decomposition_signals_build_plugin_direct() -> None:
    from repograph.plugins.demand_analyzers.decomposition_signals.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_demand_analyzers_config_flow_build_plugin_direct() -> None:
    from repograph.plugins.demand_analyzers.config_flow.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_demand_analyzers_module_component_signals_build_plugin_direct() -> None:
    from repograph.plugins.demand_analyzers.module_component_signals.plugin import build_plugin

    assert build_plugin().plugin_id()


# --- exporters ---


def test_exporters_docs_mirror_build_plugin_direct() -> None:
    from repograph.plugins.exporters.docs_mirror.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_exporters_pathway_contexts_build_plugin_direct() -> None:
    from repograph.plugins.exporters.pathway_contexts.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_exporters_agent_guide_build_plugin_direct() -> None:
    from repograph.plugins.exporters.agent_guide.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_exporters_modules_build_plugin_direct() -> None:
    from repograph.plugins.exporters.modules.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_exporters_pathways_build_plugin_direct() -> None:
    from repograph.plugins.exporters.pathways.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_exporters_summary_build_plugin_direct() -> None:
    from repograph.plugins.exporters.summary.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_exporters_config_registry_build_plugin_direct() -> None:
    from repograph.plugins.exporters.config_registry.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_exporters_invariants_build_plugin_direct() -> None:
    from repograph.plugins.exporters.invariants.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_exporters_event_topology_build_plugin_direct() -> None:
    from repograph.plugins.exporters.event_topology.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_exporters_async_tasks_build_plugin_direct() -> None:
    from repograph.plugins.exporters.async_tasks.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_exporters_entry_points_build_plugin_direct() -> None:
    from repograph.plugins.exporters.entry_points.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_exporters_doc_warnings_build_plugin_direct() -> None:
    from repograph.plugins.exporters.doc_warnings.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_exporters_runtime_overlay_summary_build_plugin_direct() -> None:
    from repograph.plugins.exporters.runtime_overlay_summary.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_exporters_observed_runtime_findings_build_plugin_direct() -> None:
    from repograph.plugins.exporters.observed_runtime_findings.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_exporters_report_surfaces_build_plugin_direct() -> None:
    from repograph.plugins.exporters.report_surfaces.plugin import build_plugin

    assert build_plugin().plugin_id()


# --- evidence producers ---


def test_evidence_producers_declared_dependencies_build_plugin_direct() -> None:
    from repograph.plugins.evidence_producers.declared_dependencies.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_evidence_producers_runtime_overlay_build_plugin_direct() -> None:
    from repograph.plugins.evidence_producers.runtime_overlay.plugin import build_plugin

    assert build_plugin().plugin_id()


# --- dynamic analyzers ---


def test_dynamic_analyzers_runtime_overlay_build_plugin_direct() -> None:
    from repograph.plugins.dynamic_analyzers.runtime_overlay.plugin import build_plugin

    assert build_plugin().plugin_id()


def test_dynamic_analyzers_coverage_tracer_build_plugin_direct() -> None:
    from repograph.plugins.dynamic_analyzers.coverage_tracer.plugin import build_plugin

    assert build_plugin().plugin_id()


# --- pipeline phase (no ``build_plugin``) ---


def test_pipeline_phases_no_op_build_no_op_direct() -> None:
    from repograph.plugins.pipeline_phases.no_op.plugin import build_no_op

    assert build_no_op().phase_id == "phase.experimental_no_op"
