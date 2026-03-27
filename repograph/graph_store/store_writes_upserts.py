"""GraphStore node upserts (File, Folder, Function, Class, Variable, Import)."""
from __future__ import annotations

from typing import Any

from repograph.core.models import (
    FileNode,
    FolderNode,
    FunctionNode,
    ClassNode,
    VariableNode,
    ImportNode,
)
from repograph.graph_store.store_base import GraphStoreBase
from repograph.graph_store.store_utils import _j, _ts


class GraphStoreNodeUpserts(GraphStoreBase):
    def upsert_file(self, node: FileNode) -> None:
        self._require_conn().execute(
            """
            MERGE (f:File {id: $id})
            SET f.path = $path,
                f.abs_path = $abs_path,
                f.name = $name,
                f.extension = $ext,
                f.language = $lang,
                f.size_bytes = $size,
                f.line_count = $lines,
                f.source_hash = $hash,
                f.is_test = $is_test,
                f.is_config = $is_config,
                f.indexed_at = $ts
            """,
            {
                "id": node.id, "path": node.path, "abs_path": node.abs_path,
                "name": node.name, "ext": node.extension, "lang": node.language,
                "size": node.size_bytes, "lines": node.line_count,
                "hash": node.source_hash, "is_test": node.is_test,
                "is_config": node.is_config, "ts": _ts(node.indexed_at),
            }
        )

    def upsert_folder(self, node: FolderNode) -> None:
        self._require_conn().execute(
            """
            MERGE (f:Folder {id: $id})
            SET f.path = $path, f.name = $name, f.depth = $depth
            """,
            {"id": node.id, "path": node.path, "name": node.name, "depth": node.depth}
        )

    def preload_runtime_overlay_for_file_paths(self, file_paths: list[str]) -> None:
        """Bulk-load runtime overlay columns for existing Functions in ``file_paths``.

        Uses a single ``WHERE f.file_path IN $fps`` query instead of N per-file
        queries.  Call at the start of parse phase; pair with
        :meth:`clear_runtime_overlay_prefetch`.
        """
        self._runtime_overlay_prefetch = {}
        if not file_paths:
            return
        try:
            rows = self.query(
                "MATCH (f:Function) WHERE f.file_path IN $fps RETURN f.id, "
                "f.runtime_observed_for_hash, f.runtime_observed, "
                "f.runtime_observed_calls, f.runtime_observed_at",
                {"fps": file_paths},
            )
            for r in rows:
                self._runtime_overlay_prefetch[r[0]] = (r[1], r[2], r[3], r[4])
        except Exception:
            # Prefetch is an optimisation — fall back to per-function queries in upsert_function
            self._runtime_overlay_prefetch = {}

    def clear_runtime_overlay_prefetch(self) -> None:
        self._runtime_overlay_prefetch = None

    def upsert_function(self, fn: FunctionNode) -> None:
        rows: list[list[Any]]
        prefetch = getattr(self, "_runtime_overlay_prefetch", None)
        if prefetch is not None and fn.id in prefetch:
            t = prefetch[fn.id]
            rows = [[t[0], t[1], t[2], t[3]]]
        else:
            rows = self.query(
                "MATCH (f:Function {id: $id}) RETURN f.runtime_observed_for_hash, "
                "f.runtime_observed, f.runtime_observed_calls, f.runtime_observed_at",
                {"id": fn.id},
            )
        if not rows:
            rt_obs, rt_calls, rt_at, rt_for = False, 0, "", ""
        else:
            rt_hash = rows[0][0] or ""
            if rt_hash and rt_hash != fn.source_hash:
                rt_obs, rt_calls, rt_at, rt_for = False, 0, "", ""
            elif rt_hash == fn.source_hash:
                rt_obs = bool(rows[0][1])
                rt_calls = int(rows[0][2] or 0)
                rt_at = rows[0][3] or ""
                rt_for = rt_hash
            else:
                rt_obs, rt_calls, rt_at, rt_for = False, 0, "", ""

        self._require_conn().execute(
            """
            MERGE (f:Function {id: $id})
            SET f.name = $name,
                f.qualified_name = $qname,
                f.file_path = $fp,
                f.line_start = $ls,
                f.line_end = $le,
                f.signature = $sig,
                f.docstring = $doc,
                f.is_method = $is_method,
                f.is_async = $is_async,
                f.is_exported = $is_exported,
                f.is_entry_point = $is_ep,
                f.entry_score = $score,
                f.is_dead = $is_dead,
                f.community_id = $comm,
                f.source_hash = $hash,
                f.decorators = $decs,
                f.param_names = $params,
                f.return_type = $ret,
                f.is_closure_returned = $is_cret,
                f.is_script_global = $is_sg,
                f.is_module_caller = $is_mc,
                f.is_test = $is_test,
                f.dead_context = $dctx,
                f.runtime_observed = $rt_obs,
                f.runtime_observed_calls = $rt_calls,
                f.runtime_observed_at = $rt_at,
                f.runtime_observed_for_hash = $rt_for,
                f.route_path = $route_path,
                f.http_method = $http_method
            """,
            {
                "id": fn.id, "name": fn.name, "qname": fn.qualified_name,
                "fp": fn.file_path, "ls": fn.line_start, "le": fn.line_end,
                "sig": fn.signature, "doc": fn.docstring or "",
                "is_method": fn.is_method, "is_async": fn.is_async,
                "is_exported": fn.is_exported, "is_ep": fn.is_entry_point,
                "score": fn.entry_score, "is_dead": fn.is_dead,
                "comm": fn.community_id or "", "hash": fn.source_hash,
                "decs": _j(fn.decorators), "params": _j(fn.param_names),
                "ret": fn.return_type or "",
                "is_cret": fn.is_closure_returned,
                "is_sg": fn.is_script_global,
                "is_mc": fn.is_module_caller,
                "is_test": getattr(fn, "is_test", False),
                "dctx": getattr(fn, "dead_context", "") or "",
                "rt_obs": rt_obs,
                "rt_calls": rt_calls,
                "rt_at": rt_at,
                "rt_for": rt_for,
                "route_path": fn.route_path,
                "http_method": fn.http_method,
            }
        )

    def upsert_class(self, cls: ClassNode) -> None:
        self._require_conn().execute(
            """
            MERGE (c:Class {id: $id})
            SET c.name = $name,
                c.qualified_name = $qname,
                c.file_path = $fp,
                c.line_start = $ls,
                c.line_end = $le,
                c.docstring = $doc,
                c.base_names = $bases,
                c.is_exported = $exported,
                c.source_hash = $hash,
                c.community_id = $comm,
                c.is_type_referenced = $type_ref
            """,
            {
                "id": cls.id, "name": cls.name, "qname": cls.qualified_name,
                "fp": cls.file_path, "ls": cls.line_start, "le": cls.line_end,
                "doc": cls.docstring or "", "bases": _j(cls.base_names),
                "exported": cls.is_exported, "hash": cls.source_hash,
                "comm": cls.community_id or "", "type_ref": False,
            }
        )

    def upsert_variable(self, var: VariableNode) -> None:
        self._require_conn().execute(
            """
            MERGE (v:Variable {id: $id})
            SET v.name = $name,
                v.function_id = $fid,
                v.file_path = $fp,
                v.line_number = $ln,
                v.inferred_type = $itype,
                v.is_parameter = $is_param,
                v.is_return = $is_ret,
                v.value_repr = $val
            """,
            {
                "id": var.id, "name": var.name, "fid": var.function_id,
                "fp": var.file_path, "ln": var.line_number,
                "itype": var.inferred_type or "", "is_param": var.is_parameter,
                "is_ret": var.is_return, "val": var.value_repr or "",
            }
        )

    def upsert_import(self, imp: ImportNode) -> None:
        self._require_conn().execute(
            """
            MERGE (i:Import {id: $id})
            SET i.file_path = $fp,
                i.raw_statement = $raw,
                i.module_path = $mod,
                i.resolved_path = $res,
                i.imported_names = $names,
                i.is_wildcard = $wild,
                i.line_number = $ln
            """,
            {
                "id": imp.id, "fp": imp.file_path, "raw": imp.raw_statement,
                "mod": imp.module_path, "res": imp.resolved_path or "",
                "names": _j(imp.imported_names), "wild": imp.is_wildcard,
                "ln": imp.line_number,
            }
        )
