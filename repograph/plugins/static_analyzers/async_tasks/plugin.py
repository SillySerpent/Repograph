"""Async task spawn graph static analyzer.

Detects asyncio.create_task / ensure_future call sites. All logic lives in this
plugin; meta JSON is written under ``.repograph/meta/``.
"""
from __future__ import annotations

import ast
import os
from dataclasses import asdict, dataclass

from repograph.core.models import ParsedFile
from repograph.core.plugin_framework import PluginManifest, StaticAnalyzerPlugin
from repograph.graph_store.store import GraphStore
from repograph.plugins.utils import write_meta_json

@dataclass
class AsyncTaskSpawn:
    spawner_fn_id: str
    spawner_file: str
    coroutine_name: str
    task_name: str | None
    confidence: float


_KNOWN = frozenset({"create_task", "ensure_future"})


def extract_async_tasks(parsed_files: list[ParsedFile]) -> list[AsyncTaskSpawn]:
    """Detect asyncio task spawns in Python sources."""
    out: list[AsyncTaskSpawn] = []
    for pf in parsed_files:
        if pf.file_record.language != "python":
            continue
        abs_p = pf.file_record.abs_path
        if not abs_p or not os.path.exists(abs_p):
            continue
        try:
            src = open(abs_p, encoding="utf-8", errors="replace").read()
            tree = ast.parse(src)
        except (OSError, SyntaxError, UnicodeError):
            continue

        fn_by_line = {ln: fn.id for fn in pf.functions for ln in range(fn.line_start, fn.line_end + 1)}

        class _Visitor(ast.NodeVisitor):
            def visit_Call(self, node: ast.Call) -> None:
                name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else None
                if name not in _KNOWN:
                    self.generic_visit(node)
                    return
                caller_id = fn_by_line.get(node.lineno)
                if not caller_id:
                    self.generic_visit(node)
                    return
                coro = ""
                if node.args:
                    try:
                        coro = ast.unparse(node.args[0])[:120]
                    except AttributeError:
                        coro = ast.dump(node.args[0])[:120]
                tname = next((str(kw.value.value) for kw in node.keywords if kw.arg == "name" and isinstance(kw.value, ast.Constant)), None)
                coro_name = coro.split("(")[0].strip().split(".")[-1] or "coro"
                out.append(AsyncTaskSpawn(
                    spawner_fn_id=caller_id,
                    spawner_file=pf.file_record.path,
                    coroutine_name=coro_name,
                    task_name=tname,
                    confidence=0.9 if tname else 0.6,
                ))
                self.generic_visit(node)

        _Visitor().visit(tree)
    return out


class AsyncTasksAnalyzerPlugin(StaticAnalyzerPlugin):
    """Detects asyncio.create_task / ensure_future spawn sites."""

    manifest = PluginManifest(
        id="static_analyzer.async_tasks",
        name="Async tasks analyzer",
        kind="static_analyzer",
        description="Detects asyncio task spawn sites across the codebase.",
        requires=("symbols",),
        produces=("findings.async_tasks",),
        hooks=("on_graph_built",),
        order=230,
        after=("static_analyzer.pathways",),
    )

    def analyze(self, store: GraphStore | None = None, repograph_dir: str = "", parsed=None, **kwargs) -> list[dict]:
        if store is None:
            service = kwargs.get("service")
            if service is None:
                return []
            return service.async_tasks()
        rows = [asdict(s) for s in extract_async_tasks(parsed or [])]
        if repograph_dir:
            write_meta_json(repograph_dir, "async_tasks.json", rows)
        return rows


def build_plugin() -> AsyncTasksAnalyzerPlugin:
    return AsyncTasksAnalyzerPlugin()
