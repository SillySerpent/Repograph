"""Phase 7 — Variables: persist variable nodes and build FLOWS_INTO edges."""
from __future__ import annotations

from repograph.core.models import ParsedFile, FlowsIntoEdge
from repograph.graph_store.store import GraphStore
from repograph.variables.extractor import VariableScopeExtractor
from repograph.variables.resolver import ArgumentChainResolver


def run(
    parsed_files: list[ParsedFile],
    store: GraphStore,
    reparse_paths: set[str] | None = None,
) -> None:
    """
    Build FLOWS_INTO edges connecting caller variables to callee parameters
    at each call site.

    In incremental mode, pass reparse_paths (the set of file paths that were
    re-parsed this cycle).  When provided, variables for unchanged files are
    loaded from the graph store instead of re-parsing those files from disk,
    so that cross-file FLOWS_INTO edges involving unchanged files are not lost.
    """
    # Variables for reparsed files are already persisted in phase 3.
    # Build extractor from the freshly-parsed files.
    extractor = VariableScopeExtractor(parsed_files)

    # In incremental mode: also load variables for unchanged files from the store
    # so that FLOWS_INTO resolution covers the full call graph.
    if reparse_paths is not None:
        for var_dict in store.get_variables_not_in_files(reparse_paths):
            extractor.add_from_dict(var_dict)

    # Load all call edges from store for resolution (includes unchanged-file edges)
    call_edges = store.get_all_call_edges()
    resolver = ArgumentChainResolver(extractor, call_edges, parsed_files)
    flows_edges = resolver.build_flows_into_edges()

    for edge in flows_edges:
        try:
            store.insert_flows_into_edge(edge)
        except Exception:
            pass
