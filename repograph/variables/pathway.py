"""VariableThreadBuilder — assembles named variable threads across call chains."""
from __future__ import annotations

from collections import defaultdict, Counter

from repograph.core.models import VariableThread


class VariableThreadBuilder:
    """
    After all FLOWS_INTO edges exist, trace connected chains of variable
    nodes and name each chain.
    """

    def build(
        self,
        pathway_function_ids: list[str],
        flows_into_edges: list[dict],
        variable_nodes: dict[str, dict],  # var_id -> {name, function_id, ...}
    ) -> list[VariableThread]:
        """
        Build variable threads for a pathway.

        Args:
            pathway_function_ids: ordered list of function IDs in the pathway
            flows_into_edges: all FLOWS_INTO edges from the store
            variable_nodes: dict of variable_id -> variable dict

        Returns:
            List of VariableThread objects
        """
        step_index = {fid: i for i, fid in enumerate(pathway_function_ids)}
        pathway_func_set = set(pathway_function_ids)

        # Filter edges where both endpoints belong to pathway functions
        relevant_edges: list[dict] = []
        for e in flows_into_edges:
            from_var = variable_nodes.get(e.get("from_var") or e.get("from", ""))
            to_var = variable_nodes.get(e.get("to_var") or e.get("to", ""))
            if from_var and to_var:
                if (from_var.get("function_id") in pathway_func_set
                        and to_var.get("function_id") in pathway_func_set):
                    relevant_edges.append(e)

        if not relevant_edges:
            return []

        # Union-Find on variable IDs to find connected components
        all_var_ids: set[str] = set()
        for e in relevant_edges:
            fv = e.get("from_var") or e.get("from", "")
            tv = e.get("to_var") or e.get("to", "")
            all_var_ids.add(fv)
            all_var_ids.add(tv)

        parent = {vid: vid for vid in all_var_ids}

        def find(x: str) -> str:
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent[x], parent[x])
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for e in relevant_edges:
            fv = e.get("from_var") or e.get("from", "")
            tv = e.get("to_var") or e.get("to", "")
            union(fv, tv)

        # Group vars by component
        components: dict[str, list[str]] = defaultdict(list)
        for vid in all_var_ids:
            root = find(vid)
            components[root].append(vid)

        threads: list[VariableThread] = []
        for root, var_ids in components.items():
            if len(var_ids) < 2:
                continue  # single-node component — not a thread

            # Name by most common variable name in component
            names = [variable_nodes[vid]["name"] for vid in var_ids if vid in variable_nodes]
            names = [n for n in names if n and n != "__return__"]
            if not names:
                continue
            thread_name = Counter(names).most_common(1)[0][0]

            # Build ordered steps
            steps: list[tuple[int, str, str]] = []
            for vid in var_ids:
                vdata = variable_nodes.get(vid)
                if not vdata:
                    continue
                func_id = vdata.get("function_id", "")
                order = step_index.get(func_id, -1)
                if order >= 0:
                    steps.append((order, func_id, vid))

            steps.sort(key=lambda x: x[0])
            if steps:
                threads.append(VariableThread(name=thread_name, steps=steps))

        return threads
