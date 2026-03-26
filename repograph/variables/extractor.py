"""VariableScopeExtractor — per-function variable scope lookup."""
from __future__ import annotations

from collections import defaultdict

from repograph.core.models import ParsedFile, VariableNode


class VariableScopeExtractor:
    """
    Provides fast lookup of VariableNodes by (function_id, variable_name).
    Built from the ParsedFile list produced by the parse phase.
    """

    def __init__(self, parsed_files: list[ParsedFile]) -> None:
        # function_id -> {var_name -> list[VariableNode]}
        self._scope: dict[str, dict[str, list[VariableNode]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._params: dict[str, list[VariableNode]] = defaultdict(list)

        for pf in parsed_files:
            for var in pf.variables:
                self._scope[var.function_id][var.name].append(var)
                if var.is_parameter:
                    self._params[var.function_id].append(var)


    def add_from_dict(self, d: dict) -> None:
        """Add a variable from a store dict into the extractor.

        Used in incremental mode to load variables from unchanged files
        without re-parsing those files from disk.
        Accepts the dict format returned by GraphStore.get_variables_not_in_files().
        """
        from repograph.core.models import VariableNode
        var = VariableNode(
            id=d["id"],
            name=d["name"],
            function_id=d["function_id"],
            file_path=d["file_path"],
            line_number=d["line_number"] or 0,
            inferred_type=d.get("inferred_type") or None,
            is_parameter=bool(d.get("is_parameter")),
            is_return=bool(d.get("is_return")),
            value_repr=d.get("value_repr") or None,
        )
        self._scope[var.function_id][var.name].append(var)
        if var.is_parameter:
            self._params[var.function_id].append(var)

    def lookup(self, function_id: str, var_name: str) -> VariableNode | None:
        """Return the first matching variable in a function's scope."""
        matches = self._scope[function_id].get(var_name, [])
        return matches[0] if matches else None

    def get_params(self, function_id: str) -> list[VariableNode]:
        """Return all parameter VariableNodes for a function, in definition order."""
        return sorted(
            self._params.get(function_id, []), key=lambda v: v.line_number
        )

    def get_param_by_index(self, function_id: str, index: int) -> VariableNode | None:
        """Return the i-th parameter of a function (0-indexed, skipping self/cls)."""
        params = self.get_params(function_id)
        if index < len(params):
            return params[index]
        return None

    def get_param_by_name(self, function_id: str, name: str) -> VariableNode | None:
        """Return a parameter by its keyword name."""
        for var in self._params.get(function_id, []):
            if var.name == name:
                return var
        return None

    def all_vars_for_function(self, function_id: str) -> list[VariableNode]:
        return [
            v
            for vlist in self._scope.get(function_id, {}).values()
            for v in vlist
        ]
