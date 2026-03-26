"""TypeScript/TSX parser — extends JavaScript parser with type annotations."""
from __future__ import annotations

from typing import Any

import tree_sitter as ts

_ts_ts: Any = None
try:
    import tree_sitter_typescript as _ts_ts
    _TS_AVAILABLE = True
except ImportError:
    _TS_AVAILABLE = False

from repograph.plugins.parsers.javascript.javascript_parser import JavaScriptParser
from repograph.parsing.base import node_text, find_all_nodes, first_child_of_type
from repograph.core.models import ParsedFile, FileRecord, FunctionNode, NodeID
from repograph.utils.hashing import hash_source_slice


class TypeScriptParser(JavaScriptParser):
    language_name = "typescript"

    def _build_parser(self) -> ts.Parser:
        if not _TS_AVAILABLE:
            # Fall back to JS parser if TS grammar not installed
            import tree_sitter_javascript as tsjs
            lang = ts.Language(tsjs.language())
        else:
            assert _ts_ts is not None
            lang = ts.Language(_ts_ts.language_typescript())
        return ts.Parser(lang)

    def parse(self, source: bytes, file_record: FileRecord) -> ParsedFile:
        try:
            tree = self.parser.parse(source)
            pf = self._extract(tree.root_node, source, file_record)
            # Enrich functions with TypeScript return type annotations
            source_str = source.decode("utf-8", errors="replace")
            self._enrich_ts_types(tree.root_node, source, pf)
            return pf
        except Exception:
            return ParsedFile(file_record=file_record)

    def _enrich_ts_types(
        self, root: ts.Node, source: bytes, pf: ParsedFile
    ) -> None:
        """Extract TypeScript type annotations and enrich existing FunctionNodes."""
        fn_by_line: dict[int, FunctionNode] = {fn.line_start: fn for fn in pf.functions}
        for node in find_all_nodes(root, "function_declaration"):
            line = node.start_point[0] + 1
            if line not in fn_by_line:
                continue
            fn = fn_by_line[line]
            # TypeScript return type: ): ReturnType {
            type_ann = node.child_by_field_name("return_type")
            if type_ann:
                fn.return_type = node_text(type_ann, source).lstrip(":").strip()
            # TypeScript parameter types
            params_node = node.child_by_field_name("parameters")
            if params_node:
                typed_params = []
                for child in params_node.children:
                    if child.type in ("required_parameter", "optional_parameter"):
                        id_node = first_child_of_type(child, "identifier")
                        if id_node:
                            typed_params.append(node_text(id_node, source))
                if typed_params:
                    fn.param_names = typed_params
