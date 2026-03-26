"""JavaScript/JSX parser using tree-sitter for RepoGraph.

Builds ``ParsedFile`` records: functions, classes, imports, variables, and
``CallSite`` entries with ``callee_text`` taken from the AST call expression.
"""
from __future__ import annotations

import tree_sitter as ts
import tree_sitter_javascript as tsjs

from repograph.parsing.base import (
    BaseParser, find_all_nodes, find_all_nodes_multi,
    node_text, first_child_of_type, get_docstring,
)
from repograph.core.models import (
    ParsedFile, FileRecord, FunctionNode, ClassNode,
    ImportNode, CallSite, VariableNode, NodeID,
)
from repograph.utils.hashing import hash_source_slice, hash_string


class JavaScriptParser(BaseParser):
    language_name = "javascript"

    def _build_parser(self) -> ts.Parser:
        lang = ts.Language(tsjs.language())
        return ts.Parser(lang)

    def parse(self, source: bytes, file_record: FileRecord) -> ParsedFile:
        try:
            tree = self.parser.parse(source)
            return self._extract(tree.root_node, source, file_record)
        except Exception:
            return ParsedFile(file_record=file_record)

    def _extract(self, root: ts.Node, source: bytes, file_record: FileRecord) -> ParsedFile:
        pf = ParsedFile(file_record=file_record)
        source_str = source.decode("utf-8", errors="replace")

        # Classes
        for cn in find_all_nodes(root, "class_declaration"):
            cls = self._extract_class(cn, source, source_str, file_record)
            if cls:
                pf.classes.append(cls)

        # Functions — multiple AST node types
        func_types = {
            "function_declaration", "function_expression",
            "arrow_function", "method_definition",
        }
        self._extract_functions(root, source, source_str, file_record, pf, class_prefix="")

        # Imports
        for node in find_all_nodes_multi(root, {"import_statement", "call_expression"}):
            imp = self._extract_import(node, source, file_record)
            if imp:
                pf.imports.append(imp)

        # Module-scope calls (parity with Python): synthetic __module__ sentinel
        self._ensure_module_sentinel(root, source, file_record, pf)

        # Call sites
        self._extract_call_sites(root, source, file_record, pf)

        # Tag module-scope functions as script globals.
        # If this file is loaded via <script src="..."> (determined later by
        # Phase 4 HTML scanner), those functions become implicitly callable
        # from any co-loaded file in the same HTML page.
        _tag_script_globals(pf)

        return pf

    def _extract_functions(
        self, node: ts.Node, source: bytes, source_str: str,
        file_record: FileRecord, pf: ParsedFile, class_prefix: str,
    ) -> None:
        for child in node.children:
            if child.type == "function_declaration":
                fn = self._extract_function_decl(child, source, source_str, file_record, class_prefix)
                if fn:
                    pf.functions.append(fn)
                    pf.variables.extend(self._extract_params(child, source, file_record, fn.id))
                    body = child.child_by_field_name("body")
                    if body:
                        self._extract_functions(body, source, source_str, file_record, pf, class_prefix)
            elif child.type == "lexical_declaration":
                # const foo = () => {} or const foo = function() {}
                for decl in find_all_nodes(child, "variable_declarator"):
                    name_node = decl.child_by_field_name("name")
                    val = decl.child_by_field_name("value")
                    if name_node and val and val.type in ("arrow_function", "function_expression"):
                        fn = self._extract_arrow_or_expr(name_node, val, source, source_str, file_record, class_prefix)
                        if fn:
                            pf.functions.append(fn)
                            pf.variables.extend(self._extract_params(val, source, file_record, fn.id))
            elif child.type == "class_declaration":
                name_node = child.child_by_field_name("name")
                cname = node_text(name_node, source) if name_node else ""
                body = child.child_by_field_name("body")
                if body and cname:
                    self._extract_functions(body, source, source_str, file_record, pf, class_prefix=cname + ".")
            elif child.type == "method_definition":
                fn = self._extract_method(child, source, source_str, file_record, class_prefix)
                if fn:
                    fn.is_method = True
                    pf.functions.append(fn)
                    pf.variables.extend(self._extract_params(child, source, file_record, fn.id))
            else:
                self._extract_functions(child, source, source_str, file_record, pf, class_prefix)

    def _extract_function_decl(
        self, node: ts.Node, source: bytes, source_str: str,
        file_record: FileRecord, class_prefix: str,
    ) -> FunctionNode | None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return None
        name = node_text(name_node, source)
        return self._make_function(name, node, source, source_str, file_record, class_prefix)

    def _extract_arrow_or_expr(
        self, name_node: ts.Node, val_node: ts.Node,
        source: bytes, source_str: str,
        file_record: FileRecord, class_prefix: str,
    ) -> FunctionNode | None:
        name = node_text(name_node, source)
        return self._make_function(name, val_node, source, source_str, file_record, class_prefix)

    def _extract_method(
        self, node: ts.Node, source: bytes, source_str: str,
        file_record: FileRecord, class_prefix: str,
    ) -> FunctionNode | None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return None
        name = node_text(name_node, source)
        return self._make_function(name, node, source, source_str, file_record, class_prefix)

    def _make_function(
        self, name: str, node: ts.Node, source: bytes, source_str: str,
        file_record: FileRecord, class_prefix: str,
    ) -> FunctionNode | None:
        if not name:
            return None
        qualified_name = class_prefix + name
        is_async = any(c.type == "async" for c in node.children)

        params_node = node.child_by_field_name("parameters") or node.child_by_field_name("parameter")
        params_text = node_text(params_node, source) if params_node else "()"
        signature = f"{'async ' if is_async else ''}function {name}{params_text}"

        line_start = node.start_point[0] + 1
        line_end = node.end_point[0] + 1
        src_hash = hash_source_slice(source_str, line_start, line_end)
        is_exported = not name.startswith("_")

        fn_id = NodeID.make_function_id(file_record.path, qualified_name)
        return FunctionNode(
            id=fn_id, name=name, qualified_name=qualified_name,
            file_path=file_record.path, line_start=line_start, line_end=line_end,
            signature=signature, docstring=None, is_method=False, is_async=is_async,
            is_exported=is_exported, decorators=[], param_names=[],
            return_type=None, source_hash=src_hash,
            is_test=file_record.is_test,
        )

    def _extract_class(
        self, node: ts.Node, source: bytes, source_str: str,
        file_record: FileRecord,
    ) -> ClassNode | None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return None
        name = node_text(name_node, source)

        base_names: list[str] = []
        # tree-sitter-javascript uses class_heritage node, not a named field
        for child in node.children:
            if child.type == "class_heritage":
                for c in child.children:
                    if c.type == "identifier":
                        base_names.append(node_text(c, source))

        line_start = node.start_point[0] + 1
        line_end = node.end_point[0] + 1
        src_hash = hash_source_slice(source_str, line_start, line_end)

        return ClassNode(
            id=NodeID.make_class_id(file_record.path, name),
            name=name, qualified_name=name,
            file_path=file_record.path, line_start=line_start, line_end=line_end,
            docstring=None, base_names=base_names,
            is_exported=not name.startswith("_"), source_hash=src_hash,
        )

    def _extract_import(self, node: ts.Node, source: bytes, file_record: FileRecord) -> ImportNode | None:
        line = node.start_point[0] + 1
        raw = node_text(node, source)

        if node.type == "import_statement":
            # import foo from 'bar'; import { a, b } from 'baz'
            source_node = node.child_by_field_name("source")
            module_path = ""
            if source_node:
                raw_mod = node_text(source_node, source).strip("'\"")
                module_path = raw_mod

            imported_names: list[str] = []
            for child in node.children:
                if child.type == "import_clause":
                    for ic in child.children:
                        if ic.type == "identifier":
                            imported_names.append(node_text(ic, source))
                        elif ic.type == "named_imports":
                            for spec in ic.children:
                                if spec.type == "import_specifier":
                                    id_node = first_child_of_type(spec, "identifier")
                                    if id_node:
                                        imported_names.append(node_text(id_node, source))

            if not module_path:
                return None
            return ImportNode(
                id=NodeID.make_import_id(file_record.path, module_path, line),
                file_path=file_record.path, raw_statement=raw,
                module_path=module_path, resolved_path=None,
                imported_names=imported_names, is_wildcard=False,
                line_number=line,
            )

        elif node.type == "call_expression":
            # require('foo') pattern
            fn_node = node.child_by_field_name("function")
            if fn_node and node_text(fn_node, source) == "require":
                args = node.child_by_field_name("arguments")
                if args:
                    for arg in args.children:
                        if arg.type == "string":
                            module_path = node_text(arg, source).strip("'\"")
                            return ImportNode(
                                id=NodeID.make_import_id(file_record.path, module_path, line),
                                file_path=file_record.path, raw_statement=raw,
                                module_path=module_path, resolved_path=None,
                                imported_names=[], is_wildcard=False, line_number=line,
                            )
        return None

    def _extract_params(
        self, func_node: ts.Node, source: bytes,
        file_record: FileRecord, function_id: str,
    ) -> list[VariableNode]:
        params = []
        params_node = (func_node.child_by_field_name("parameters")
                       or func_node.child_by_field_name("parameter"))
        if not params_node:
            return params
        for child in params_node.children:
            if child.type == "identifier":
                name = node_text(child, source)
                params.append(VariableNode(
                    id=NodeID.make_variable_id(file_record.path, function_id, name),
                    name=name, function_id=function_id,
                    file_path=file_record.path, line_number=child.start_point[0] + 1,
                    inferred_type=None, is_parameter=True, is_return=False, value_repr=None,
                ))
        return params

    def _ensure_module_sentinel(
        self,
        root: ts.Node,
        source: bytes,
        file_record: FileRecord,
        pf: ParsedFile,
    ) -> None:
        """If any call expression sits at module scope, append ``__module__`` sentinel.

        Matches Python's module-level call attribution: Phase 5 edges use the
        sentinel as caller for top-level ``foo()`` / ``bar()`` invocations.
        """
        module_id = NodeID.make_function_id(file_record.path, "__module__")
        if any(fn.id == module_id for fn in pf.functions):
            return
        for call_node in find_all_nodes(root, "call_expression"):
            fn_node = call_node.child_by_field_name("function")
            if not fn_node:
                continue
            if node_text(fn_node, source) == "require":
                continue
            if self._find_enclosing_function(call_node, pf.functions) is not None:
                continue
            pf.functions.append(
                FunctionNode(
                    id=module_id,
                    name="__module__",
                    qualified_name="__module__",
                    file_path=file_record.path,
                    line_start=0,
                    line_end=0,
                    signature="__module__()",
                    docstring=None,
                    is_method=False,
                    is_async=False,
                    is_exported=False,
                    decorators=[],
                    param_names=[],
                    return_type=None,
                    source_hash="",
                    is_module_caller=True,
                    is_test=file_record.is_test,
                )
            )
            return

    def _extract_call_sites(
        self, root: ts.Node, source: bytes,
        file_record: FileRecord, pf: ParsedFile,
    ) -> None:
        module_id = NodeID.make_function_id(file_record.path, "__module__")
        for call_node in find_all_nodes(root, "call_expression"):
            fn_node = call_node.child_by_field_name("function")
            if not fn_node:
                continue
            callee_text = node_text(fn_node, source)
            if callee_text == "require":
                continue

            caller_id = self._find_enclosing_function(call_node, pf.functions)
            if caller_id is None:
                if any(f.id == module_id for f in pf.functions):
                    caller_id = module_id
                else:
                    continue

            args_node = call_node.child_by_field_name("arguments")
            pos_args: list[str] = []
            if args_node:
                for arg in args_node.children:
                    if arg.type not in (",", "(", ")", "comment") and arg.is_named:
                        pos_args.append(node_text(arg, source))

            pf.call_sites.append(CallSite(
                caller_function_id=caller_id,
                callee_text=callee_text,
                call_site_line=call_node.start_point[0] + 1,
                argument_exprs=pos_args,
                keyword_args={},
                file_path=file_record.path,
            ))

    def _find_enclosing_function(self, node: ts.Node, functions: list[FunctionNode]) -> str | None:
        line = node.start_point[0] + 1
        best: FunctionNode | None = None
        best_span = 999999
        for fn in functions:
            if fn.line_start <= line <= fn.line_end:
                span = fn.line_end - fn.line_start
                if span < best_span:
                    best_span = span
                    best = fn
        return best.id if best else None


# ---------------------------------------------------------------------------
# Script-global tagging
# ---------------------------------------------------------------------------

def _tag_script_globals(pf: "ParsedFile") -> None:
    """Mark module-scope JS functions as ``is_script_global = True``.

    A function is module-scope when it is not a class method and not nested
    inside another function.  To determine nesting, we use the line ranges
    already recorded on each FunctionNode: a function F is nested inside G
    if G's line range strictly contains F's line range.

    We build a set of function IDs that are contained within another
    function, then mark all remaining non-method functions as script globals.
    """
    # Build a fast lookup of all function line ranges (excluding methods,
    # since methods are always inside a class body, not a function body).
    non_method_fns = [f for f in pf.functions if not f.is_method and not f.is_module_caller]

    # Find nested function IDs: a function whose range is fully inside another.
    nested_ids: set[str] = set()
    for i, fn in enumerate(non_method_fns):
        for j, other in enumerate(non_method_fns):
            if i == j:
                continue
            # fn is nested in other if other strictly contains fn's range
            if (other.line_start < fn.line_start
                    and fn.line_end <= other.line_end):
                nested_ids.add(fn.id)
                break

    for fn in pf.functions:
        if fn.is_method or fn.is_module_caller:
            continue
        if fn.id not in nested_ids:
            fn.is_script_global = True
