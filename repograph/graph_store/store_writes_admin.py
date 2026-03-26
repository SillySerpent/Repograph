"""GraphStore topology clears, deletes, flag updates, and warning nodes."""
from __future__ import annotations

from typing import Any

from repograph.core.models import DuplicateSymbolGroup, DocSymbolWarning
from repograph.graph_store.store_base import GraphStoreBase


class GraphStoreAdminWrites(GraphStoreBase):
    # Topology-level clears (used before incremental re-run of topology phases)

    def clear_communities(self) -> None:
        """Delete all Community nodes and MEMBER_OF/CLASS_IN edges before re-detection.
        Called before p09_communities in incremental sync to prevent ghost accumulation."""
        self._require_conn().execute("MATCH (c:Community) DETACH DELETE c")

    def clear_pathways(self) -> None:
        """Delete all Pathway nodes and related edges before re-assembly.
        Called before pathway rebuild plugins run in incremental sync to prevent ghost accumulation."""
        self._require_conn().execute("MATCH (p:Pathway) DETACH DELETE p")

    def clear_processes(self) -> None:
        """Delete all Process nodes and STEP_IN_PROCESS edges before re-scoring.
        Called before p10_processes in incremental sync to prevent ghost accumulation."""
        self._require_conn().execute("MATCH (p:Process) DETACH DELETE p")

    # Type-reference tracking (Phase 8 output)

    def mark_class_type_referenced(self, class_id: str) -> None:
        """Mark a class as referenced via type annotation -- prevents false dead-code."""
        try:
            self._require_conn().execute(
                "MATCH (c:Class {id: $id}) SET c.is_type_referenced = true",
                {"id": class_id}
            )
        except Exception:
            pass

    # Deletion (for incremental sync)

    def delete_file_nodes(self, file_path: str) -> None:
        """Delete a File node and all its related nodes/edges for a given path."""
        from repograph.core.models import NodeID
        file_id = NodeID.make_file_id(file_path)

        self._require_conn().execute(
            "MATCH (fn:Function {file_path: $fp}) DETACH DELETE fn",
            {"fp": file_path}
        )
        self._require_conn().execute(
            "MATCH (c:Class {file_path: $fp}) DETACH DELETE c",
            {"fp": file_path}
        )
        self._require_conn().execute(
            "MATCH (v:Variable {file_path: $fp}) DETACH DELETE v",
            {"fp": file_path}
        )
        self._require_conn().execute(
            "MATCH (i:Import {file_path: $fp}) DETACH DELETE i",
            {"fp": file_path}
        )
        self._require_conn().execute(
            "MATCH (f:File {id: $id}) DETACH DELETE f",
            {"id": file_id}
        )

    def update_function_flags(
        self,
        function_id: str,
        is_dead: bool | None = None,
        dead_code_tier: str | None = None,
        dead_code_reason: str | None = None,
        dead_context: str | None = None,
        is_entry_point: bool | None = None,
        entry_score: float | None = None,
        entry_score_base: float | None = None,
        entry_score_multipliers: str | None = None,
        entry_callee_count: int | None = None,
        entry_caller_count: int | None = None,
        community_id: str | None = None,
        is_closure_returned: bool | None = None,
        is_script_global: bool | None = None,
        is_module_caller: bool | None = None,
    ) -> None:
        sets = []
        params: dict[str, Any] = {"id": function_id}
        if is_dead is not None:
            sets.append("f.is_dead = $is_dead"); params["is_dead"] = is_dead
        if dead_code_tier is not None:
            sets.append("f.dead_code_tier = $dct"); params["dct"] = dead_code_tier
        if dead_code_reason is not None:
            sets.append("f.dead_code_reason = $dcr"); params["dcr"] = dead_code_reason
        if dead_context is not None:
            sets.append("f.dead_context = $dctx"); params["dctx"] = dead_context
        if is_entry_point is not None:
            sets.append("f.is_entry_point = $is_ep"); params["is_ep"] = is_entry_point
        if entry_score is not None:
            sets.append("f.entry_score = $score"); params["score"] = entry_score
        if entry_score_base is not None:
            sets.append("f.entry_score_base = $esb"); params["esb"] = entry_score_base
        if entry_score_multipliers is not None:
            sets.append("f.entry_score_multipliers = $esm"); params["esm"] = entry_score_multipliers
        if entry_callee_count is not None:
            sets.append("f.entry_callee_count = $ecc"); params["ecc"] = entry_callee_count
        if entry_caller_count is not None:
            sets.append("f.entry_caller_count = $ecr"); params["ecr"] = entry_caller_count
        if community_id is not None:
            sets.append("f.community_id = $comm"); params["comm"] = community_id
        if is_closure_returned is not None:
            sets.append("f.is_closure_returned = $is_cret"); params["is_cret"] = is_closure_returned
        if is_script_global is not None:
            sets.append("f.is_script_global = $is_sg"); params["is_sg"] = is_script_global
        if is_module_caller is not None:
            sets.append("f.is_module_caller = $is_mc"); params["is_mc"] = is_module_caller
        if not sets:
            return
        self._require_conn().execute(
            f"MATCH (f:Function {{id: $id}}) SET {', '.join(sets)}",
            params
        )

    def apply_runtime_observation(
        self,
        function_id: str,
        *,
        calls: int,
        observed_at_iso: str,
        source_hash: str,
    ) -> None:
        """Mark a function as observed at runtime for this ``source_hash`` revision.

        Clears static dead-code flags so the next sync does not re-apply dead
        classification until the source changes (invalidated in ``upsert_function``).
        """
        self._require_conn().execute(
            """
            MATCH (f:Function {id: $id})
            SET f.runtime_observed = true,
                f.runtime_observed_calls = $calls,
                f.runtime_observed_at = $at,
                f.runtime_observed_for_hash = $h,
                f.is_dead = false,
                f.dead_code_tier = '',
                f.dead_code_reason = '',
                f.dead_context = ''
            """,
            {
                "id": function_id,
                "calls": calls,
                "at": observed_at_iso,
                "h": source_hash,
            },
        )

    def upsert_duplicate_symbol(self, group: DuplicateSymbolGroup) -> None:
        import json as _json
        self._require_conn().execute(
            """
            MERGE (d:DuplicateSymbol {id: $id})
            SET d.name = $name,
                d.kind = $kind,
                d.occurrence_count = $cnt,
                d.file_paths = $fps,
                d.severity = $sev,
                d.reason = $reason,
                d.is_superseded = $sup,
                d.canonical_path = $canonical,
                d.superseded_paths = $sup_paths
            """,
            {
                "id": group.id, "name": group.name, "kind": group.kind,
                "cnt": group.occurrence_count,
                "fps": _json.dumps(group.file_paths),
                "sev": group.severity, "reason": group.reason,
                "sup": group.is_superseded,
                "canonical": group.canonical_path or "",
                "sup_paths": _json.dumps(group.superseded_paths or []),
            }
        )

    def clear_duplicate_symbols(self) -> None:
        """Remove all DuplicateSymbol nodes (before re-running phase 11b)."""
        try:
            self._require_conn().execute("MATCH (d:DuplicateSymbol) DELETE d")
        except Exception:
            pass

    def upsert_doc_warning(self, warning: DocSymbolWarning) -> None:
        """Insert or replace a DocSymbolWarning node."""
        self._require_conn().execute(
            """
            MERGE (w:DocWarning {id: $id})
            SET w.doc_path = $dp,
                w.line_number = $ln,
                w.symbol_text = $sym,
                w.warning_type = $wt,
                w.severity = $sev,
                w.context_snippet = $ctx
            """,
            {
                "id": warning.id, "dp": warning.doc_path,
                "ln": warning.line_number, "sym": warning.symbol_text,
                "wt": warning.warning_type, "sev": warning.severity,
                "ctx": warning.context_snippet,
            }
        )

    def clear_doc_warnings(self) -> None:
        """Remove all DocWarning nodes (before re-running phase 14)."""
        try:
            self._require_conn().execute("MATCH (w:DocWarning) DELETE w")
        except Exception:
            pass

    def update_class_community(self, class_id: str, community_id: str) -> None:
        self._require_conn().execute(
            "MATCH (c:Class {id: $id}) SET c.community_id = $comm",
            {"id": class_id, "comm": community_id}
        )

    def update_pathway_context(self, pathway_id: str, context_doc: str) -> None:
        self._require_conn().execute(
            "MATCH (p:Pathway {id: $id}) SET p.context_doc = $ctx",
            {"id": pathway_id, "ctx": context_doc}
        )
