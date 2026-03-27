"""Python language parser using tree-sitter for RepoGraph.

Extracts:
- function_definition (sync + async, nested, decorated)
- class_definition (with bases, docstring)
- import_statement / import_from_statement
- call expressions as ``CallSite`` rows (``callee_text`` = raw callee expression)
- variable assignments, annotated assignments, parameters
- return statements
"""
from __future__ import annotations

import os
from typing import Optional

import tree_sitter as ts
import tree_sitter_python as tsp

from repograph.parsing.base import (
    BaseParser, find_all_nodes, find_all_nodes_multi,
    node_text, child_text, get_docstring, first_child_of_type,
)
from repograph.core.models import (
    ParsedFile, FileRecord, FunctionNode, ClassNode,
    ImportNode, CallSite, VariableNode, NodeID,
)
from repograph.utils.hashing import hash_source_slice, hash_string


# Single source of truth for route-like decorator suffixes and their HTTP methods.
# Matches the framework adapter detection logic exactly.
_ROUTE_DECORATOR_HTTP_METHODS: dict[str, str] = {
    ".route": "",       # Flask @app.route — method from methods=[...] arg, default GET
    ".get": "GET",
    ".post": "POST",
    ".put": "PUT",
    ".patch": "PATCH",
    ".delete": "DELETE",
    ".websocket": "WEBSOCKET",
}


class PythonParser(BaseParser):
    language_name = "python"

    def _build_parser(self) -> ts.Parser:
        lang = ts.Language(tsp.language())
        return ts.Parser(lang)

    def parse(self, source: bytes, file_record: FileRecord) -> ParsedFile:
        try:
            tree = self.parser.parse(source)
            return self._extract(tree.root_node, source, file_record)
        except Exception:
            return ParsedFile(file_record=file_record)

    # ------------------------------------------------------------------
    # Main extraction
    # ------------------------------------------------------------------

    def _extract(
        self,
        root: ts.Node,
        source: bytes,
        file_record: FileRecord,
    ) -> ParsedFile:
        pf = ParsedFile(file_record=file_record)
        source_str = source.decode("utf-8", errors="replace")

        # Pass 1: extract classes first (so we can resolve method membership)
        class_nodes = find_all_nodes(root, "class_definition")
        class_map: dict[str, ClassNode] = {}  # qualified_name -> ClassNode
        for cn in class_nodes:
            cls = self._extract_class(cn, source, source_str, file_record)
            if cls:
                pf.classes.append(cls)
                class_map[cls.qualified_name] = cls

        # Pass 2: extract functions (top-level + methods)
        # We'll do a full walk tracking the class context
        self._extract_functions_recursive(
            root, source, source_str, file_record,
            pf, class_prefix="", class_stack=[],
        )

        # Pass 3: imports
        for imp_node in find_all_nodes_multi(
            root, {"import_statement", "import_from_statement"}
        ):
            imp = self._extract_import(imp_node, source, file_record)
            if imp:
                pf.imports.append(imp)

        # Pass 4: call sites (after functions extracted so we have function IDs)
        func_id_by_range: dict[tuple[int, int], str] = {
            (fn.line_start, fn.line_end): fn.id for fn in pf.functions
        }
        self._extract_call_sites(root, source, file_record, pf, func_id_by_range)

        # Pass 5: module-level calls — calls made outside any function body.
        # These are attributed to a synthetic __module__ sentinel function so
        # Phase 11 recognises the callees as having a production caller.
        self._extract_module_level_calls(root, source, file_record, pf)

        return pf

    # ------------------------------------------------------------------
    # Function extraction
    # ------------------------------------------------------------------

    def _collect_returned_function_names(
        self,
        body: ts.Node,
        source: bytes,
    ) -> set[str]:
        """Return the set of function names that appear in any return statement
        within the given body node (at any nesting depth inside control flow).

        Detects patterns like:
            def factory(x):
                def _a(): ...
                def _b(): ...
                if x:
                    return _a   # inside if — still detected
                return _b

        Deliberately does NOT recurse into nested function or class definitions
        because those return statements belong to inner scopes, not the outer
        factory's return values.
        """
        names: set[str] = set()
        self._collect_returns_recursive(body, source, names)
        return names

    def _collect_returns_recursive(
        self,
        node: ts.Node,
        source: bytes,
        names: set[str],
    ) -> None:
        """Walk node collecting identifiers from return statements.

        Stops recursion at nested function/class definitions.
        """
        for child in node.children:
            if child.type == "return_statement":
                for rc in child.children:
                    if rc.type == "identifier":
                        names.add(node_text(rc, source))
            elif child.type in ("function_definition", "decorated_definition",
                                 "class_definition"):
                # Do not recurse into inner function/class bodies —
                # their returns belong to a different scope.
                continue
            else:
                self._collect_returns_recursive(child, source, names)

    def _extract_functions_recursive(
        self,
        node: ts.Node,
        source: bytes,
        source_str: str,
        file_record: FileRecord,
        pf: ParsedFile,
        class_prefix: str,
        class_stack: list[str],
        returned_names: set[str] | None = None,
    ) -> None:
        """Walk the tree, tracking class context for proper qualified names."""
        for child in node.children:
            if child.type in ("function_definition", "decorated_definition"):
                func_node, decorators, http_method, route_path = self._unwrap_decorated(child, source)
                if func_node and func_node.type == "function_definition":
                    fn = self._extract_function(
                        func_node, source, source_str, file_record,
                        class_prefix=class_prefix,
                        decorators=decorators,
                        http_method=http_method,
                        route_path=route_path,
                    )
                    if fn:
                        fn.is_method = bool(class_stack)
                        # Mark nested functions that are directly returned —
                        # they are reachable through the parent's return value
                        # and must not be flagged as dead code.
                        if returned_names and fn.name in returned_names:
                            fn.is_closure_returned = True
                        pf.functions.append(fn)
                        # Extract variables (params + assignments) for this function
                        fn_vars = self._extract_variables(
                            func_node, source, file_record, fn.id
                        )
                        pf.variables.extend(fn_vars)
                        # Recurse into function body for nested defs
                        body = func_node.child_by_field_name("body")
                        if body:
                            # Compute which names fn directly returns — these
                            # are fn's own closure returns, independent of the
                            # outer returned_names that belongs to fn's parent.
                            # Use a distinct variable so we never overwrite the
                            # outer scope's returned_names for sibling functions.
                            inner_returned = self._collect_returned_function_names(body, source)
                            self._extract_functions_recursive(
                                body, source, source_str, file_record,
                                pf, class_prefix=fn.qualified_name + ".",
                                class_stack=class_stack,
                                returned_names=inner_returned,
                            )

            elif child.type in ("class_definition", "decorated_definition"):
                class_node, _, _hm, _rp = self._unwrap_decorated(child, source)
                if class_node and class_node.type == "class_definition":
                    name_node = class_node.child_by_field_name("name")
                    if name_node:
                        cname = node_text(name_node, source)
                        new_prefix = (class_prefix + cname) if class_prefix else cname
                        body = class_node.child_by_field_name("body")
                        if body:
                            self._extract_functions_recursive(
                                body, source, source_str, file_record,
                                pf, class_prefix=new_prefix + ".",
                                class_stack=class_stack + [cname],
                            )
            else:
                # Recurse into other containers (if/for/with blocks at module level).
                # Pass the current returned_names so that function definitions
                # inside control-flow blocks (e.g. `if x: return _a`) are still
                # tagged as closure-returned relative to their enclosing function.
                if child.type not in ("string", "comment"):
                    self._extract_functions_recursive(
                        child, source, source_str, file_record,
                        pf, class_prefix=class_prefix,
                        class_stack=class_stack,
                        returned_names=returned_names,
                    )

    def _unwrap_decorated(
        self, node: ts.Node, source: bytes
    ) -> tuple[ts.Node | None, list[str], str, str]:
        """Unwrap a decorated_definition.

        Returns ``(inner_node, decorator_names, http_method, route_path)``
        where ``decorator_names`` contains only the callable name (arguments
        stripped), and ``http_method`` / ``route_path`` are populated when a
        route-like decorator is detected.
        """
        if node.type != "decorated_definition":
            return node, [], "", ""
        decorators: list[str] = []
        inner: ts.Node | None = None
        http_method = ""
        route_path = ""
        for child in node.children:
            if child.type == "decorator":
                dec_name, dec_http, dec_route = self._parse_decorator(child, source)
                decorators.append(dec_name)
                if dec_http or dec_route:
                    http_method = dec_http
                    route_path = dec_route
            elif child.type in ("function_definition", "class_definition"):
                inner = child
        return inner, decorators, http_method, route_path

    def _parse_decorator(
        self, decorator_node: ts.Node, source: bytes
    ) -> tuple[str, str, str]:
        """Parse a single decorator node.

        Returns ``(name, http_method, route_path)`` where name is the callable
        portion (e.g., ``router.get``), http_method and route_path are populated
        for route-like decorators.
        """
        # Find the expression inside the decorator (after the '@')
        for child in decorator_node.children:
            if child.type == "@":
                continue
            if child.type == "call":
                fn_node = child.child_by_field_name("function")
                args_node = child.child_by_field_name("arguments")
                name = node_text(fn_node, source) if fn_node else node_text(child, source)
                http_method, route_path = self._extract_route_from_decorator_name_and_args(
                    name, args_node, source
                )
                return name, http_method, route_path
            else:
                # Bare decorator (no call) — e.g., @login_required
                return node_text(child, source), "", ""
        return node_text(decorator_node, source).lstrip("@").strip(), "", ""

    def _extract_route_from_decorator_name_and_args(
        self, name: str, args_node: ts.Node | None, source: bytes
    ) -> tuple[str, str]:
        """Return (http_method, route_path) if name is a route-like decorator."""
        http_method = ""
        for suffix, method in _ROUTE_DECORATOR_HTTP_METHODS.items():
            if name.endswith(suffix):
                http_method = method
                break
        else:
            return "", ""

        route_path = ""
        if args_node is not None:
            for arg in args_node.children:
                if arg.type in ("string", "concatenated_string"):
                    raw = node_text(arg, source)
                    route_path = raw.strip("\"'")
                    break
        return http_method, route_path

    def _extract_function(
        self,
        node: ts.Node,
        source: bytes,
        source_str: str,
        file_record: FileRecord,
        class_prefix: str = "",
        decorators: list[str] | None = None,
        http_method: str = "",
        route_path: str = "",
    ) -> FunctionNode | None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return None

        name = node_text(name_node, source)
        qualified_name = class_prefix + name
        is_async = any(c.type == "async" for c in node.children)

        # Parameters
        params_node = node.child_by_field_name("parameters")
        param_names, signature_params = self._extract_params(params_node, source)

        # Return type annotation
        return_type: str | None = None
        ret_node = node.child_by_field_name("return_type")
        if ret_node:
            return_type = node_text(ret_node, source).lstrip("->").strip()

        # Signature string
        params_text = node_text(params_node, source) if params_node else "()"
        prefix = "async def" if is_async else "def"
        ret_str = f" -> {return_type}" if return_type else ""
        signature = f"{prefix} {name}{params_text}{ret_str}"

        # Line range (1-indexed)
        line_start = node.start_point[0] + 1
        line_end = node.end_point[0] + 1

        # Docstring
        body = node.child_by_field_name("body")
        docstring = get_docstring(body, source) if body else None

        # Source hash for this function slice
        src_hash = hash_source_slice(source_str, line_start, line_end)

        # Exported: not private name (no leading _) or is in __all__ (we approximate)
        is_exported = not name.startswith("_") or name.startswith("__") and name.endswith("__")

        func_id = NodeID.make_function_id(file_record.path, qualified_name)

        inline_imports: list[tuple[str, str]] = []
        if body:
            inline_imports = self._collect_inline_imports(body, source, file_record)

        return FunctionNode(
            id=func_id,
            name=name,
            qualified_name=qualified_name,
            file_path=file_record.path,
            line_start=line_start,
            line_end=line_end,
            signature=signature,
            docstring=docstring,
            is_method=False,  # set by caller
            is_async=is_async,
            is_exported=is_exported,
            decorators=decorators or [],
            param_names=param_names,
            return_type=return_type,
            source_hash=src_hash,
            is_test=file_record.is_test,
            inline_imports=inline_imports,
            http_method=http_method,
            route_path=route_path,
        )

    def _extract_params(
        self, params_node: ts.Node | None, source: bytes
    ) -> tuple[list[str], str]:
        """Return (param_name_list, params_text)."""
        if params_node is None:
            return [], "()"
        names: list[str] = []
        for child in params_node.children:
            if child.type == "identifier":
                n = node_text(child, source)
                if n != "self" and n != "cls":
                    names.append(n)
            elif child.type in ("typed_parameter", "default_parameter",
                                 "typed_default_parameter"):
                id_node = first_child_of_type(child, "identifier")
                if id_node:
                    n = node_text(id_node, source)
                    if n not in ("self", "cls"):
                        names.append(n)
            elif child.type in ("list_splat_pattern", "dictionary_splat_pattern"):
                id_node = first_child_of_type(child, "identifier")
                if id_node:
                    names.append(node_text(id_node, source))
        return names, node_text(params_node, source)

    # ------------------------------------------------------------------
    # Class extraction
    # ------------------------------------------------------------------

    def _extract_class(
        self,
        node: ts.Node,
        source: bytes,
        source_str: str,
        file_record: FileRecord,
    ) -> ClassNode | None:
        # Unwrap decorated
        decorators: list[str] = []
        actual_node = node
        if node.type == "decorated_definition":
            actual_node, decorators, _, _rp = self._unwrap_decorated(node, source)
            if actual_node is None or actual_node.type != "class_definition":
                return None

        name_node = actual_node.child_by_field_name("name")
        if not name_node:
            return None

        name = node_text(name_node, source)
        qualified_name = name  # top-level; nested handled by prefix in function pass

        # Base classes
        arg_list = actual_node.child_by_field_name("superclasses")
        base_names: list[str] = []
        if arg_list:
            for child in arg_list.children:
                if child.type in ("identifier", "attribute"):
                    base_names.append(node_text(child, source))

        line_start = actual_node.start_point[0] + 1
        line_end = actual_node.end_point[0] + 1

        body = actual_node.child_by_field_name("body")
        docstring = get_docstring(body, source) if body else None

        src_hash = hash_source_slice(source_str, line_start, line_end)
        is_exported = not name.startswith("_")

        class_id = NodeID.make_class_id(file_record.path, qualified_name)

        return ClassNode(
            id=class_id,
            name=name,
            qualified_name=qualified_name,
            file_path=file_record.path,
            line_start=line_start,
            line_end=line_end,
            docstring=docstring,
            base_names=base_names,
            is_exported=is_exported,
            source_hash=src_hash,
        )

    # ------------------------------------------------------------------
    # Import extraction
    # ------------------------------------------------------------------

    def _extract_import(
        self,
        node: ts.Node,
        source: bytes,
        file_record: FileRecord,
    ) -> ImportNode | None:
        raw = node_text(node, source)
        line_number = node.start_point[0] + 1

        if node.type == "import_statement":
            # import foo, import foo.bar
            names: list[str] = []
            module_path = ""
            for child in node.children:
                if child.type in ("dotted_name", "aliased_import"):
                    dn = first_child_of_type(child, "dotted_name") or child
                    txt = node_text(dn, source)
                    if not module_path:
                        module_path = txt
                    names.append(txt)

            imp_id = NodeID.make_import_id(file_record.path, module_path, line_number)
            return ImportNode(
                id=imp_id,
                file_path=file_record.path,
                raw_statement=raw,
                module_path=module_path,
                resolved_path=None,
                imported_names=names,
                is_wildcard=False,
                line_number=line_number,
            )

        elif node.type == "import_from_statement":
            # from foo.bar import baz, qux
            # from . import something (relative)
            # from M import X as Y  → aliases["Y"] = "X"
            module_path = ""
            level_dots = 0
            imported_names: list[str] = []
            aliases: dict[str, str] = {}   # local_alias -> original_name
            is_wildcard = False
            saw_module = False  # first dotted_name is the module

            for child in node.children:
                if child.type == "relative_import":
                    ip = first_child_of_type(child, "import_prefix")
                    if ip:
                        level_dots = node_text(ip, source).count(".")
                    dn = first_child_of_type(child, "dotted_name")
                    if dn:
                        module_path = "." * level_dots + node_text(dn, source)
                    else:
                        module_path = "." * level_dots
                    saw_module = True
                elif child.type == "dotted_name":
                    name_str = node_text(child, source)
                    if not saw_module and not module_path:
                        module_path = name_str
                        saw_module = True
                    else:
                        # It's an imported name (no alias)
                        imported_names.append(name_str.split(".")[-1])
                elif child.type in ("import_star", "wildcard_import"):
                    is_wildcard = True
                elif child.type == "aliased_import":
                    # Tree-sitter represents "X as Y" as:
                    #   aliased_import
                    #     dotted_name  (or identifier)  ← original name
                    #     "as"
                    #     identifier                    ← alias
                    # We need both to build the alias map.
                    dn = first_child_of_type(child, "dotted_name")
                    id_children = [c for c in child.children if c.type == "identifier"]

                    if dn:
                        # e.g. "from M import score_function as _score_fn"
                        original = node_text(dn, source).split(".")[-1]
                    elif id_children:
                        # e.g. "from M import foo as bar" (simple identifier, no dots)
                        original = node_text(id_children[0], source)
                    else:
                        original = None

                    if original:
                        imported_names.append(original)
                        # The alias identifier is the last identifier child when
                        # a dotted_name exists, or the second identifier when both
                        # are plain identifiers.
                        if dn and id_children:
                            alias_name = node_text(id_children[-1], source)
                            if alias_name != original:
                                aliases[alias_name] = original
                        elif len(id_children) >= 2:
                            alias_name = node_text(id_children[-1], source)
                            if alias_name != original:
                                aliases[alias_name] = original
                elif child.type == "identifier" and saw_module:
                    imported_names.append(node_text(child, source))

            if not module_path and not is_wildcard:
                return None

            imp_id = NodeID.make_import_id(file_record.path, module_path, line_number)
            return ImportNode(
                id=imp_id,
                file_path=file_record.path,
                raw_statement=raw,
                module_path=module_path,
                resolved_path=None,
                imported_names=imported_names,
                is_wildcard=is_wildcard,
                line_number=line_number,
                aliases=aliases,
            )
        return None

    def _collect_inline_imports(
        self,
        body: ts.Node,
        source: bytes,
        file_record: FileRecord,
    ) -> list[tuple[str, str]]:
        """``(module_path, symbol_name)`` for imports in this body (not nested defs)."""
        acc: list[tuple[str, str]] = []

        def walk(n: ts.Node) -> None:
            if n.type in ("function_definition", "class_definition"):
                return
            if n.type in ("import_statement", "import_from_statement"):
                imp = self._extract_import(n, source, file_record)
                if imp:
                    acc.extend(self._import_tuples_for_inline(imp))
                return
            for c in n.children:
                walk(c)

        walk(body)
        return acc

    def _import_tuples_for_inline(self, imp: ImportNode) -> list[tuple[str, str]]:
        """Map a parsed import to (module_path, name_in_target_module) pairs."""
        if imp.is_wildcard:
            return []
        raw = imp.raw_statement.strip()
        if raw.startswith("from "):
            if not imp.module_path:
                return []
            return [(imp.module_path, n.split(".")[-1]) for n in imp.imported_names]
        out: list[tuple[str, str]] = []
        for full in imp.imported_names:
            parts = full.split(".")
            if len(parts) == 1:
                out.append((parts[0], parts[0]))
            else:
                out.append((".".join(parts[:-1]), parts[-1]))
        return out

    # ------------------------------------------------------------------
    # Variable extraction
    # ------------------------------------------------------------------

    def _extract_variables(
        self,
        func_node: ts.Node,
        source: bytes,
        file_record: FileRecord,
        function_id: str,
    ) -> list[VariableNode]:
        """Extract parameters, assignments, and return vars for one function."""
        variables: list[VariableNode] = []

        # Parameters
        params_node = func_node.child_by_field_name("parameters")
        if params_node:
            for child in params_node.children:
                if child.type == "identifier":
                    pname = node_text(child, source)
                    if pname in ("self", "cls"):
                        continue
                    variables.append(self._make_var(
                        pname, function_id, file_record.path,
                        child.start_point[0] + 1,
                        is_parameter=True, inferred_type=None,
                    ))
                elif child.type in ("typed_parameter", "typed_default_parameter"):
                    id_node = first_child_of_type(child, "identifier")
                    if id_node:
                        pname = node_text(id_node, source)
                        if pname in ("self", "cls"):
                            continue
                        type_node = child.child_by_field_name("type")
                        itype = node_text(type_node, source) if type_node else None
                        variables.append(self._make_var(
                            pname, function_id, file_record.path,
                            child.start_point[0] + 1,
                            is_parameter=True, inferred_type=itype,
                        ))
                elif child.type == "default_parameter":
                    id_node = first_child_of_type(child, "identifier")
                    if id_node:
                        pname = node_text(id_node, source)
                        if pname in ("self", "cls"):
                            continue
                        variables.append(self._make_var(
                            pname, function_id, file_record.path,
                            child.start_point[0] + 1,
                            is_parameter=True, inferred_type=None,
                        ))

        # Body assignments and return statements
        body = func_node.child_by_field_name("body")
        if body:
            self._extract_body_vars(
                body, source, file_record, function_id, variables
            )

        return variables

    def _extract_body_vars(
        self,
        node: ts.Node,
        source: bytes,
        file_record: FileRecord,
        function_id: str,
        variables: list[VariableNode],
        depth: int = 0,
    ) -> None:
        """Recursively extract assignments and returns from a function body."""
        if depth > 10:
            return

        for child in node.children:
            if child.type == "assignment":
                left = child.child_by_field_name("left")
                right = child.child_by_field_name("right")
                if left and left.type == "identifier":
                    varname = node_text(left, source)
                    itype = self._infer_type_from_rhs(right, source) if right else None
                    val_repr = self._value_repr(right, source) if right else None
                    variables.append(self._make_var(
                        varname, function_id, file_record.path,
                        left.start_point[0] + 1,
                        is_parameter=False, inferred_type=itype, value_repr=val_repr,
                    ))

            elif child.type == "annotated_assignment":
                left = child.child_by_field_name("left")
                annotation = child.child_by_field_name("annotation")
                right = child.child_by_field_name("right")
                if left and left.type == "identifier":
                    varname = node_text(left, source)
                    itype = node_text(annotation, source) if annotation else None
                    val_repr = self._value_repr(right, source) if right else None
                    variables.append(self._make_var(
                        varname, function_id, file_record.path,
                        left.start_point[0] + 1,
                        is_parameter=False, inferred_type=itype, value_repr=val_repr,
                    ))

            elif child.type == "return_statement":
                # Create a synthetic return variable
                ret_children = [c for c in child.children if c.type != "return"]
                if ret_children:
                    ret_expr = ret_children[0]
                    itype = self._infer_type_from_rhs(ret_expr, source)
                    variables.append(VariableNode(
                        id=NodeID.make_variable_id(
                            file_record.path, function_id, f"__return__{child.start_point[0]}"
                        ),
                        name="__return__",
                        function_id=function_id,
                        file_path=file_record.path,
                        line_number=child.start_point[0] + 1,
                        inferred_type=itype,
                        is_parameter=False,
                        is_return=True,
                        value_repr=self._value_repr(ret_expr, source),
                    ))

            elif child.type not in ("function_definition", "class_definition",
                                     "decorated_definition", "comment", "string"):
                self._extract_body_vars(
                    child, source, file_record, function_id, variables, depth + 1
                )

    def _make_var(
        self,
        name: str,
        function_id: str,
        file_path: str,
        line_number: int,
        is_parameter: bool,
        inferred_type: str | None,
        value_repr: str | None = None,
    ) -> VariableNode:
        var_id = NodeID.make_variable_id(file_path, function_id, name)
        return VariableNode(
            id=var_id,
            name=name,
            function_id=function_id,
            file_path=file_path,
            line_number=line_number,
            inferred_type=inferred_type,
            is_parameter=is_parameter,
            is_return=False,
            value_repr=value_repr,
        )

    def _infer_type_from_rhs(self, node: ts.Node, source: bytes) -> str | None:
        """Best-effort type inference from RHS expression node."""
        if node is None:
            return None
        t = node.type
        if t == "integer":
            return "int"
        if t == "float":
            return "float"
        if t == "string":
            return "str"
        if t in ("true", "false"):
            return "bool"
        if t == "none":
            return "None"
        if t == "list":
            return "list"
        if t == "dictionary":
            return "dict"
        if t == "tuple":
            return "tuple"
        if t == "set":
            return "set"
        if t == "call":
            func_node = node.child_by_field_name("function")
            if func_node and func_node.type == "identifier":
                return node_text(func_node, source)
        return None

    def _value_repr(self, node: ts.Node, source: bytes) -> str | None:
        """Compact repr of a literal value, or None for complex expressions."""
        if node is None:
            return None
        t = node.type
        if t in ("integer", "float", "string", "true", "false", "none"):
            raw = node_text(node, source)
            return raw[:50] if len(raw) <= 50 else raw[:47] + "..."
        return None

    # ------------------------------------------------------------------
    # Call site extraction
    # ------------------------------------------------------------------

    def _extract_call_sites(
        self,
        root: ts.Node,
        source: bytes,
        file_record: FileRecord,
        pf: ParsedFile,
        func_id_by_range: dict[tuple[int, int], str],
    ) -> None:
        """Find all call expressions and attribute the call to the enclosing function."""
        call_nodes = find_all_nodes(root, "call")
        for call_node in call_nodes:
            caller_id = self._find_enclosing_function_id(
                call_node, pf.functions
            )
            if caller_id is None:
                continue  # Module-level calls not tracked (no caller function)

            func_field = call_node.child_by_field_name("function")
            if func_field is None:
                continue

            callee_text = node_text(func_field, source)
            args_node = call_node.child_by_field_name("arguments")
            pos_args: list[str] = []
            kw_args: dict[str, str] = {}

            if args_node:
                for arg in args_node.children:
                    if arg.type == "keyword_argument":
                        # keyword_argument: identifier = value
                        children = [c for c in arg.children if c.type != "="]
                        if len(children) >= 2:
                            kw_name = node_text(children[0], source)
                            kw_val = node_text(children[1], source)
                            kw_args[kw_name] = kw_val
                    elif arg.type not in (",", "(", ")", "*", "**", "comment"):
                        if arg.is_named:
                            pos_args.append(node_text(arg, source))

            pf.call_sites.append(CallSite(
                caller_function_id=caller_id,
                callee_text=callee_text,
                call_site_line=call_node.start_point[0] + 1,
                argument_exprs=pos_args,
                keyword_args=kw_args,
                file_path=file_record.path,
            ))

    def _find_enclosing_function_id(
        self,
        node: ts.Node,
        functions: list[FunctionNode],
    ) -> str | None:
        """Find the function that most tightly encloses the given node by line number."""
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

    # ------------------------------------------------------------------
    # Module-level call extraction (Pass 5)
    # ------------------------------------------------------------------

    def _extract_module_level_calls(
        self,
        root: ts.Node,
        source: bytes,
        file_record: FileRecord,
        pf: ParsedFile,
    ) -> None:
        """Extract call expressions that live at module scope (no enclosing function).

        These are attributed to a synthetic ``__module__`` sentinel function.
        The sentinel is inserted into ``pf.functions`` with ``is_module_caller=True``
        so that Phase 11 (dead code) treats its callees as having a real
        production caller rather than zero callers.

        Only immediate children of the module root and of ``if`` / ``with`` /
        ``try`` blocks at module scope are considered, not calls nested inside
        class bodies (those belong to class-level execution, not module init).
        """
        module_caller_id = NodeID.make_function_id(file_record.path, "__module__")

        # Collect call nodes at module scope into a temporary list first.
        # We only insert the sentinel function if at least one call is found,
        # so files with no module-level calls don't get an empty sentinel.
        temp_pf_calls: list = []
        seen: set[int] = set()

        # Temporarily patch pf.call_sites to collect into temp list
        original_call_sites = pf.call_sites
        pf.call_sites = temp_pf_calls  # type: ignore[assignment]
        self._collect_module_scope_calls(
            root, source, file_record, pf, module_caller_id,
            inside_function=False, seen=seen,
        )
        pf.call_sites = original_call_sites

        if not temp_pf_calls:
            # No module-level calls found — skip sentinel entirely.
            return

        # At least one module-level call exists — add the sentinel and calls.
        if not any(fn.id == module_caller_id for fn in pf.functions):
            sentinel = FunctionNode(
                id=module_caller_id,
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
            pf.functions.append(sentinel)

        pf.call_sites.extend(temp_pf_calls)

    def _collect_module_scope_calls(
        self,
        node: ts.Node,
        source: bytes,
        file_record: FileRecord,
        pf: ParsedFile,
        module_caller_id: str,
        inside_function: bool,
        seen: set[int],
    ) -> None:
        """Recursively collect call expressions at module scope only.

        Walks the AST depth-first, skipping function/class bodies (those
        calls belong to their own scope).  Picks up calls in any position:
        bare expression statements, assignment RHS, augmented assignments,
        if/for/with/try blocks, etc.
        """
        for child in node.children:
            if child.type in ("function_definition", "decorated_definition",
                              "class_definition"):
                # Do not recurse into function or class bodies — those are
                # handled by the regular call-site extraction pass.
                continue

            if child.type == "call" and not inside_function:
                call_id = child.start_point[0] * 100000 + child.start_point[1]
                if call_id not in seen:
                    seen.add(call_id)
                    func_field = child.child_by_field_name("function")
                    if func_field:
                        callee_text = node_text(func_field, source)
                        pf.call_sites.append(CallSite(
                            caller_function_id=module_caller_id,
                            callee_text=callee_text,
                            call_site_line=child.start_point[0] + 1,
                            argument_exprs=[],
                            keyword_args={},
                            file_path=file_record.path,
                        ))
                # Still recurse into call's arguments — nested calls like
                # `outer(inner())` should register `inner` as well.
                self._collect_module_scope_calls(
                    child, source, file_record, pf, module_caller_id,
                    inside_function=inside_function, seen=seen,
                )

            elif not inside_function:
                # Recurse into all other node types (assignments, expressions,
                # control flow, etc.) to find deeply nested calls at module scope.
                self._collect_module_scope_calls(
                    child, source, file_record, pf, module_caller_id,
                    inside_function=False, seen=seen,
                )
