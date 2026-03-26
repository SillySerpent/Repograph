"""ArgumentChainResolver — resolves argument binding at call sites into FLOWS_INTO edges."""
from __future__ import annotations

from repograph.core.models import ParsedFile, FlowsIntoEdge, CallSite
from repograph.variables.extractor import VariableScopeExtractor


class ArgumentChainResolver:
    """
    For each CALLS edge (caller_func → callee_func), look at the call site,
    match positional and keyword arguments to callee parameters, and emit
    FLOWS_INTO edges.
    """

    def __init__(
        self,
        extractor: VariableScopeExtractor,
        call_edges: list[dict],
        parsed_files: list[ParsedFile],
    ) -> None:
        self._extractor = extractor
        self._call_edges = call_edges

        # Build per-caller call sites: function_id -> list[CallSite]
        self._caller_sites: dict[str, list[CallSite]] = {}
        for pf in parsed_files:
            for site in pf.call_sites:
                self._caller_sites.setdefault(site.caller_function_id, []).append(site)

        # Build function param_names from call_edges caller metadata
        # We need callee param names: look them up from the extractor
        # Also build a function_id -> param_names map from parsed files
        self._func_params: dict[str, list[str]] = {}
        for pf in parsed_files:
            for fn in pf.functions:
                self._func_params[fn.id] = fn.param_names

    def build_flows_into_edges(self) -> list[FlowsIntoEdge]:
        """Return all FLOWS_INTO edges derived from call sites."""
        edges: list[FlowsIntoEdge] = []

        for call_edge in self._call_edges:
            caller_id = call_edge["from"]
            callee_id = call_edge["to"]
            call_line = call_edge.get("line", 0) or 0
            edge_confidence = call_edge.get("confidence", 1.0) or 1.0

            # Find the matching call site in the caller
            site = self._find_call_site(caller_id, callee_id, call_line)
            if site is None:
                continue

            # Get callee param names
            callee_params = self._func_params.get(callee_id, [])
            if not callee_params:
                callee_params = [
                    p.name for p in self._extractor.get_params(callee_id)
                ]

            # Positional argument binding
            for i, arg_expr in enumerate(site.argument_exprs):
                if not arg_expr.isidentifier():
                    continue  # skip complex expressions
                if i >= len(callee_params):
                    break

                caller_var = self._extractor.lookup(caller_id, arg_expr)
                callee_param_name = callee_params[i]
                callee_var = self._extractor.get_param_by_name(callee_id, callee_param_name)

                if caller_var and callee_var:
                    edges.append(FlowsIntoEdge(
                        from_variable_id=caller_var.id,
                        to_variable_id=callee_var.id,
                        via_argument=callee_param_name,
                        call_site_line=site.call_site_line,
                        confidence=edge_confidence * 0.9,
                    ))

            # Keyword argument binding
            for kwarg_name, kwarg_expr in site.keyword_args.items():
                if not kwarg_expr.isidentifier():
                    continue

                caller_var = self._extractor.lookup(caller_id, kwarg_expr)
                callee_var = self._extractor.get_param_by_name(callee_id, kwarg_name)

                if caller_var and callee_var:
                    edges.append(FlowsIntoEdge(
                        from_variable_id=caller_var.id,
                        to_variable_id=callee_var.id,
                        via_argument=kwarg_name,
                        call_site_line=site.call_site_line,
                        confidence=edge_confidence * 0.9,
                    ))

        return edges

    def _find_call_site(
        self, caller_id: str, callee_id: str, call_line: int
    ) -> CallSite | None:
        """Find the CallSite in caller_id that matches the call edge (approximate by line)."""
        sites = self._caller_sites.get(caller_id, [])
        if not sites:
            return None

        # Prefer exact line match
        for site in sites:
            if site.call_site_line == call_line:
                return site

        # Fallback: return first site in caller (for simple one-call functions)
        return sites[0] if len(sites) == 1 else None
