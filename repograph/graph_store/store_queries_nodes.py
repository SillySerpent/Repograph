"""GraphStore node-detail and symbol-shape query helpers."""
from __future__ import annotations

import json
import re

from repograph.graph_store.store_base import GraphStoreBase


def _parse_init_type_annotations(signature: str) -> dict[str, str]:
    """Extract ``param_name → type_annotation`` from a raw ``__init__`` signature."""
    result: dict[str, str] = {}
    match = re.search(r"\(\s*(.*?)\)\s*(?:->.*)?$", signature, re.DOTALL)
    if not match:
        return result
    params_str = match.group(1)

    depth = 0
    current: list[str] = []
    segments: list[str] = []
    for ch in params_str:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            segments.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        segments.append("".join(current).strip())

    for segment in segments:
        segment = segment.strip()
        if not segment or segment in ("self", "cls", "*", "/", "**kwargs", "*args"):
            continue
        if "=" in segment:
            segment = segment.split("=")[0].strip()
        if ":" in segment:
            name, _, annotation = segment.partition(":")
            result[name.strip().lstrip("*")] = annotation.strip()
        else:
            result[segment.lstrip("*")] = ""
    return result


class GraphStoreNodeQueries(GraphStoreBase):
    def get_all_functions(self) -> list[dict]:
        rows = self.query(
            """
            MATCH (f:Function)
            RETURN f.id, f.name, f.qualified_name, f.file_path,
                   f.line_start, f.line_end, f.is_entry_point, f.entry_score,
                   f.is_dead, f.decorators, f.param_names, f.signature,
                   f.is_method, f.is_closure_returned, f.is_script_global,
                   f.is_module_caller, f.is_test, f.dead_code_tier, f.dead_code_reason,
                   f.source_hash, f.runtime_observed, f.runtime_observed_for_hash,
                   f.runtime_observed_calls, f.runtime_observed_at
            """
        )
        return [
            {
                "id": row[0],
                "name": row[1],
                "qualified_name": row[2],
                "file_path": row[3],
                "line_start": row[4],
                "line_end": row[5],
                "is_entry_point": row[6],
                "entry_score": row[7],
                "is_dead": row[8],
                "decorators": json.loads(row[9]) if row[9] else [],
                "param_names": json.loads(row[10]) if row[10] else [],
                "signature": row[11],
                "is_method": row[12],
                "is_closure_returned": row[13] or False,
                "is_script_global": row[14] or False,
                "is_module_caller": row[15] or False,
                "is_test": row[16] if row[16] is not None else False,
                "dead_code_tier": row[17] or "",
                "dead_code_reason": row[18] or "",
                "source_hash": row[19] or "",
                "runtime_observed": bool(row[20]) if row[20] is not None else False,
                "runtime_observed_for_hash": row[21] or "",
                "runtime_observed_calls": int(row[22] or 0),
                "runtime_observed_at": row[23] or "",
            }
            for row in rows
        ]

    def get_function_by_id(self, function_id: str) -> dict | None:
        rows = self.query(
            """
            MATCH (f:Function {id: $id})
            RETURN f.id, f.name, f.qualified_name, f.file_path,
                   f.line_start, f.line_end, f.signature, f.docstring,
                   f.is_entry_point, f.is_dead, f.decorators, f.param_names,
                   f.return_type, f.entry_score, f.community_id, f.is_test
            """,
            {"id": function_id},
        )
        if not rows:
            return None
        row = rows[0]
        return {
            "id": row[0],
            "name": row[1],
            "qualified_name": row[2],
            "file_path": row[3],
            "line_start": row[4],
            "line_end": row[5],
            "signature": row[6],
            "docstring": row[7],
            "is_entry_point": row[8],
            "is_dead": row[9],
            "decorators": json.loads(row[10]) if row[10] else [],
            "param_names": json.loads(row[11]) if row[11] else [],
            "return_type": row[12],
            "entry_score": row[13],
            "community_id": row[14],
            "is_test": row[15] if row[15] is not None else False,
        }

    def get_variables_for_function(self, function_id: str) -> list[dict]:
        rows = self.query(
            """
            MATCH (v:Variable {function_id: $fid})
            RETURN v.id, v.name, v.inferred_type, v.is_parameter, v.is_return, v.line_number
            """,
            {"fid": function_id},
        )
        return [
            {
                "id": row[0],
                "name": row[1],
                "inferred_type": row[2],
                "is_parameter": row[3],
                "is_return": row[4],
                "line_number": row[5],
            }
            for row in rows
        ]

    def get_constructor_deps(self, class_name: str, depth: int = 2) -> dict:
        """Return ``__init__`` parameter names and type annotations for a class."""
        _ = depth
        rows = self.query(
            "MATCH (c:Class) WHERE c.name = $n RETURN c.id LIMIT 1",
            {"n": class_name},
        )
        if not rows:
            return {
                "class": class_name,
                "parameters": [],
                "signature": "",
                "error": "class not found",
            }
        class_id = rows[0][0]
        rows2 = self.query(
            """
            MATCH (c:Class {id: $cid})-[:HAS_METHOD]->(f:Function)
            WHERE f.name = '__init__'
            RETURN f.param_names, f.signature
            LIMIT 1
            """,
            {"cid": class_id},
        )
        if not rows2:
            return {"class": class_name, "parameters": [], "signature": ""}

        raw_params = json.loads(rows2[0][0]) if rows2[0][0] else []
        signature = rows2[0][1] or ""
        if raw_params and raw_params[0] in ("self", "cls"):
            raw_params = list(raw_params[1:])

        type_map: dict[str, str] = {}
        try:
            type_map = _parse_init_type_annotations(signature)
        except Exception:
            pass

        parameters = [{"name": param, "type": type_map.get(param, "")} for param in raw_params]
        return {
            "class": class_name,
            "parameters": parameters,
            "signature": signature,
        }
