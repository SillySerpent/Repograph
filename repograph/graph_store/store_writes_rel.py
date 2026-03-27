"""GraphStore relationship inserts and pathway/community topology writes."""
from __future__ import annotations

import json
from typing import Any

from repograph.core.models import (
    CallEdge,
    ImportEdge,
    FlowsIntoEdge,
    ExtendsEdge,
    ImplementsEdge,
    CommunityNode,
    CoupledWithEdge,
    PathwayDoc,
)
from repograph.graph_store.store_base import GraphStoreBase
from repograph.graph_store.store_utils import _j, _ts, _hash_content
from repograph.observability import get_logger

_logger = get_logger(__name__, subsystem="graph_store")


class GraphStoreRelWrites(GraphStoreBase):
    # Edge insertions — use safe string interpolation because KuzuDB's
    # Cypher parser rejects $params in multi-node MATCH queries.

    def clear_call_edge_prefetch(self) -> None:
        """Clear batched CALLS reads (see :meth:`prefetch_call_edges_for_pairs`)."""
        self._call_edge_prefetch = None

    def prefetch_call_edges_for_pairs(self, pairs: list[tuple[str, str]]) -> None:
        """Bulk-load existing CALLS rows for deduped (from_id, to_id) pairs (O2)."""
        self._call_edge_prefetch = {}
        if not pairs:
            return
        uniq = list(dict.fromkeys(pairs))
        from repograph.config import PREFETCH_CHUNK_SIZE
        chunk = PREFETCH_CHUNK_SIZE
        for i in range(0, len(uniq), chunk):
            part = uniq[i : i + chunk]
            conds = " OR ".join(
                f"(a.id = '{self._esc(a)}' AND b.id = '{self._esc(b)}')" for a, b in part
            )
            if not self._calls_extra_lines:
                q = (
                    f"MATCH (a:Function)-[r:CALLS]->(b:Function) WHERE {conds} "
                    "RETURN a.id, b.id, r.confidence, r.reason"
                )
                rows = self.query(q)
                seen = {(r[0], r[1]) for r in rows}
                for r in rows:
                    self._call_edge_prefetch[(r[0], r[1])] = [[r[2], r[3]]]
                for key in part:
                    if key not in seen:
                        self._call_edge_prefetch[key] = []
            else:
                q = (
                    f"MATCH (a:Function)-[r:CALLS]->(b:Function) WHERE {conds} "
                    "RETURN a.id, b.id, r.call_site_line, r.extra_site_lines, "
                    "r.confidence, r.reason"
                )
                rows = self.query(q)
                seen = {(r[0], r[1]) for r in rows}
                for r in rows:
                    self._call_edge_prefetch[(r[0], r[1])] = [
                        [r[2], r[3], r[4], r[5]]
                    ]
                for key in part:
                    if key not in seen:
                        self._call_edge_prefetch[key] = []

    def _fetch_calls_rows(self, from_id: str, to_id: str) -> list[list[Any]]:
        """Existing CALLS row(s) for a pair, using prefetch when configured."""
        pc = getattr(self, "_call_edge_prefetch", None)
        if pc is not None:
            key = (from_id, to_id)
            if key in pc:
                return pc.pop(key)
        if not self._calls_extra_lines:
            return self.query(
                "MATCH (a:Function {id: $from})-[r:CALLS]->(b:Function {id: $to}) "
                "RETURN r.confidence, r.reason",
                {"from": from_id, "to": to_id},
            )
        return self.query(
            "MATCH (a:Function {id: $from})-[r:CALLS]->(b:Function {id: $to}) "
            "RETURN r.call_site_line, r.extra_site_lines, r.confidence, r.reason",
            {"from": from_id, "to": to_id},
        )

    def insert_import_edge(self, edge: ImportEdge) -> None:
        fid = self._esc(edge.from_file_id)
        tid = self._esc(edge.to_file_id)
        syms = self._esc(_j(edge.specific_symbols))
        wild = "true" if edge.is_wildcard else "false"
        self._exec_rel(
            f"MATCH (a:File {{id:'{fid}'}}),(b:File {{id:'{tid}'}}) "
            f"MERGE (a)-[r:IMPORTS]->(b) "
            f"SET r.specific_symbols='{syms}', r.is_wildcard={wild}, "
            f"r.line_number={edge.line_number}, r.confidence={edge.confidence}"
        )

    def insert_call_edge(self, edge: CallEdge) -> None:
        """Insert or merge a CALLS edge between two Function nodes.

        Merge policy:
        - If no edge exists: create it with the supplied confidence and reason.
        - If an edge already exists: keep the HIGHER confidence value and the
          reason that corresponds to it.  This ensures that a high-confidence
          inline_import edge written by Phase 4 is not silently downgraded to
          fuzzy/0.3 when Phase 5 re-discovers the same call via name matching.

        INVARIANT: Never reduces the confidence of an existing edge.
        """
        fid = self._esc(edge.from_function_id)
        tid = self._esc(edge.to_function_id)
        args = self._esc(_j(edge.argument_names))
        reason = self._esc(edge.reason)
        conf = edge.confidence
        line = int(edge.call_site_line)

        if not self._calls_extra_lines:
            # Read existing edge confidence first
            existing = self._fetch_calls_rows(edge.from_function_id, edge.to_function_id)
            if existing:
                existing_conf = existing[0][0] or 0.0
                if existing_conf >= conf:
                    # Existing edge is already at least as good — only update line
                    self._exec_rel(
                        f"MATCH (a:Function {{id:'{fid}'}})-[r:CALLS]->(b:Function {{id:'{tid}'}}) "
                        f"SET r.call_site_line={line}"
                    )
                    return
                # New edge has higher confidence — fall through to overwrite
            self._exec_rel(
                f"MATCH (a:Function {{id:'{fid}'}}),(b:Function {{id:'{tid}'}}) "
                f"MERGE (a)-[r:CALLS]->(b) "
                f"SET r.call_site_line={line}, r.argument_names='{args}', "
                f"r.confidence={conf}, r.reason='{reason}'"
            )
            return

        rows = self._fetch_calls_rows(edge.from_function_id, edge.to_function_id)
        if not rows:
            ex = self._esc("[]")
            self._exec_rel(
                f"MATCH (a:Function {{id:'{fid}'}}),(b:Function {{id:'{tid}'}}) "
                f"MERGE (a)-[r:CALLS]->(b) "
                f"SET r.call_site_line={line}, r.extra_site_lines='{ex}', "
                f"r.argument_names='{args}', r.confidence={conf}, r.reason='{reason}'"
            )
            return

        primary = int(rows[0][0])
        raw = rows[0][1]
        existing_conf = rows[0][2] or 0.0
        existing_reason = rows[0][3] or edge.reason

        # Resolve confidence: keep the higher value and its associated reason
        if existing_conf >= conf:
            final_conf = existing_conf
            final_reason = self._esc(existing_reason)
        else:
            final_conf = conf
            final_reason = reason

        try:
            extra_list = json.loads(raw) if raw else []
        except (json.JSONDecodeError, TypeError) as parse_exc:
            _logger.warning(
                "extra_site_lines JSON parse failed — falling back to empty list; "
                "call-site history for this edge may be incomplete",
                from_id=edge.from_function_id,
                to_id=edge.to_function_id,
                exc_msg=str(parse_exc),
            )
            extra_list = []
        if not isinstance(extra_list, list):
            extra_list = []
        merged: set[int] = {primary, line}
        for x in extra_list:
            try:
                merged.add(int(x))
            except (TypeError, ValueError):
                pass
        sorted_lines = sorted(merged)
        new_primary = sorted_lines[0]
        others = [x for x in sorted_lines if x != new_primary]
        extra_json = self._esc(_j(others))

        # INVARIANT: confidence must never decrease. Guard defensively before write.
        if final_conf < existing_conf:
            _logger.warning(
                "confidence invariant violation detected — clamping to existing value",
                from_id=edge.from_function_id,
                to_id=edge.to_function_id,
                existing_conf=existing_conf,
                computed_final_conf=final_conf,
            )
            final_conf = existing_conf

        self._exec_rel(
            f"MATCH (a:Function {{id:'{fid}'}})-[r:CALLS]->(b:Function {{id:'{tid}'}}) "
            f"SET r.call_site_line={new_primary}, r.extra_site_lines='{extra_json}', "
            f"r.argument_names='{args}', r.confidence={final_conf}, r.reason='{final_reason}'"
        )

    def insert_flows_into_edge(self, edge: FlowsIntoEdge) -> None:
        fid = self._esc(edge.from_variable_id)
        tid = self._esc(edge.to_variable_id)
        via = self._esc(edge.via_argument)
        self._exec_rel(
            f"MATCH (a:Variable {{id:'{fid}'}}),(b:Variable {{id:'{tid}'}}) "
            f"MERGE (a)-[r:FLOWS_INTO]->(b) "
            f"SET r.via_argument='{via}', r.call_site_line={edge.call_site_line}, "
            f"r.confidence={edge.confidence}"
        )

    def insert_extends_edge(self, edge: ExtendsEdge) -> None:
        fid = self._esc(edge.from_class_id)
        tid = self._esc(edge.to_class_id)
        self._exec_rel(
            f"MATCH (a:Class {{id:'{fid}'}}),(b:Class {{id:'{tid}'}}) "
            f"MERGE (a)-[r:EXTENDS]->(b) SET r.confidence={edge.confidence}"
        )

    def insert_defines_edge(self, file_id: str, function_id: str) -> None:
        fid = self._esc(file_id)
        fnid = self._esc(function_id)
        self._exec_rel(
            f"MATCH (f:File {{id:'{fid}'}}),(fn:Function {{id:'{fnid}'}}) "
            f"MERGE (f)-[:DEFINES]->(fn)"
        )

    def insert_defines_class_edge(self, file_id: str, class_id: str) -> None:
        fid = self._esc(file_id)
        cid = self._esc(class_id)
        self._exec_rel(
            f"MATCH (f:File {{id:'{fid}'}}),(c:Class {{id:'{cid}'}}) "
            f"MERGE (f)-[:DEFINES_CLASS]->(c)"
        )

    def insert_has_method_edge(self, class_id: str, function_id: str) -> None:
        cid = self._esc(class_id)
        fid = self._esc(function_id)
        self._exec_rel(
            f"MATCH (c:Class {{id:'{cid}'}}),(fn:Function {{id:'{fid}'}}) "
            f"MERGE (c)-[:HAS_METHOD]->(fn)"
        )

    def insert_class_in_community_edge(self, class_id: str, community_id: str) -> None:
        cid = self._esc(class_id)
        comid = self._esc(community_id)
        self._exec_rel(
            f"MATCH (c:Class {{id:'{cid}'}}),(com:Community {{id:'{comid}'}}) "
            f"MERGE (c)-[:CLASS_IN]->(com)"
        )

    def insert_implements_edge(self, edge: ImplementsEdge) -> None:
        fid = self._esc(edge.from_class_id)
        tid = self._esc(edge.to_class_id)
        self._exec_rel(
            f"MATCH (a:Class {{id:'{fid}'}}),(b:Class {{id:'{tid}'}}) "
            f"MERGE (a)-[r:IMPLEMENTS]->(b) SET r.confidence={edge.confidence}"
        )

    def insert_var_in_pathway_edge(
        self,
        variable_id: str,
        pathway_id: str,
        thread_name: str,
        thread_step: int,
    ) -> None:
        vid = self._esc(variable_id)
        pid = self._esc(pathway_id)
        tname = self._esc(thread_name)
        self._exec_rel(
            f"MATCH (v:Variable {{id:'{vid}'}}),(p:Pathway {{id:'{pid}'}}) "
            f"MERGE (v)-[r:VAR_IN_PATHWAY]->(p) "
            f"SET r.thread_name='{tname}', r.thread_step={thread_step}"
        )

    def insert_folder_file_edges(self, folder_id: str, file_id: str) -> None:
        foid = self._esc(folder_id)
        fiid = self._esc(file_id)
        self._exec_rel(
            f"MATCH (fo:Folder {{id:'{foid}'}}),(fi:File {{id:'{fiid}'}}) "
            f"MERGE (fo)-[:CONTAINS]->(fi) MERGE (fi)-[:IN_FOLDER]->(fo)"
        )

    def upsert_community(self, comm: CommunityNode) -> None:
        self._require_conn().execute(
            """
            MERGE (c:Community {id: $id})
            SET c.label = $label, c.cohesion = $cohesion, c.member_count = $count
            """,
            {"id": comm.id, "label": comm.label, "cohesion": comm.cohesion, "count": comm.member_count}
        )

    def insert_member_of_edge(self, function_id: str, community_id: str) -> None:
        fid = self._esc(function_id)
        cid = self._esc(community_id)
        self._exec_rel(
            f"MATCH (f:Function {{id:'{fid}'}}),(c:Community {{id:'{cid}'}}) "
            f"MERGE (f)-[:MEMBER_OF]->(c)"
        )

    def upsert_pathway(self, pathway: PathwayDoc) -> None:
        threads_json = _j([
            {"name": t.name, "steps": t.steps}
            for t in pathway.variable_threads
        ])
        self._require_conn().execute(
            """
            MERGE (p:Pathway {id: $id})
            SET p.name = $name,
                p.display_name = $dname,
                p.description = $descr,
                p.entry_file = $efile,
                p.entry_function = $efunc,
                p.terminal_type = $ttype,
                p.file_count = $fc,
                p.step_count = $sc,
                p.source = $src,
                p.confidence = $conf,
                p.importance_score = $imp,
                p.variable_threads = $vt,
                p.context_doc = $ctx,
                p.context_hash = $chash,
                p.generated_at = $gat
            """,
            {
                "id": pathway.id, "name": pathway.name,
                "dname": pathway.display_name, "descr": pathway.description,
                "efile": pathway.entry_file, "efunc": pathway.entry_function,
                "ttype": pathway.terminal_type,
                "fc": len(pathway.participating_files), "sc": len(pathway.steps),
                "src": pathway.source, "conf": pathway.confidence,
                "imp": pathway.importance_score,
                "vt": threads_json, "ctx": pathway.context_doc,
                "chash": _hash_content(pathway.context_doc or "")[:16],
                "gat": _ts(pathway.generated_at),
            }
        )

    def insert_step_in_pathway(self, function_id: str, pathway_id: str, order: int, role: str) -> None:
        fid = self._esc(function_id)
        pid = self._esc(pathway_id)
        role_e = self._esc(role)
        self._exec_rel(
            f"MATCH (f:Function {{id:'{fid}'}}),(p:Pathway {{id:'{pid}'}}) "
            f"MERGE (f)-[r:STEP_IN_PATHWAY]->(p) "
            f"SET r.step_order={order}, r.role='{role_e}'"
        )

    def insert_coupled_with_edge(self, edge: CoupledWithEdge) -> None:
        fid = self._esc(edge.from_file_id)
        tid = self._esc(edge.to_file_id)
        self._exec_rel(
            f"MATCH (a:File {{id:'{fid}'}}),(b:File {{id:'{tid}'}}) "
            f"MERGE (a)-[r:COUPLED_WITH]->(b) "
            f"SET r.change_count={edge.change_count}, r.strength={edge.strength}"
        )

    def update_function_layer_role(
        self,
        fn_id: str,
        layer: str,
        role: str = "",
        http_method: str = "",
        route_path: str = "",
    ) -> None:
        """Set layer/role/http classification fields on a Function node (schema v1.6)."""
        fid = self._esc(fn_id)
        l_e = self._esc(layer)
        r_e = self._esc(role)
        hm_e = self._esc(http_method)
        rp_e = self._esc(route_path)
        try:
            self._require_conn().execute(
                f"MATCH (f:Function {{id:'{fid}'}}) "
                f"SET f.layer='{l_e}', f.role='{r_e}', "
                f"f.http_method='{hm_e}', f.route_path='{rp_e}'"
            )
        except Exception as exc:
            _logger.warning(
                "update_function_layer_role failed",
                fn_id=fn_id,
                exc_type=type(exc).__name__,
                exc_msg=str(exc),
            )

    def insert_makes_http_call_edge(
        self,
        from_id: str,
        to_id: str,
        http_method: str,
        url_pattern: str,
        confidence: float,
        reason: str,
    ) -> None:
        """Insert a MAKES_HTTP_CALL edge (schema v1.6) from a Python caller to an HTTP handler."""
        fid = self._esc(from_id)
        tid = self._esc(to_id)
        hm_e = self._esc(http_method)
        up_e = self._esc(url_pattern)
        rs_e = self._esc(reason)
        self._exec_rel(
            f"MATCH (a:Function {{id:'{fid}'}}),(b:Function {{id:'{tid}'}}) "
            f"MERGE (a)-[r:MAKES_HTTP_CALL]->(b) "
            f"SET r.http_method='{hm_e}', r.url_pattern='{up_e}', "
            f"r.confidence={confidence}, r.reason='{rs_e}'"
        )
