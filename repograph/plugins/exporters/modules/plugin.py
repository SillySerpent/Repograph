from __future__ import annotations

"""Module exporter plugin — all logic lives here. Fires on: on_export."""

"""Phase 16 — Module Index: per-directory structural overview.

Aggregates file, class, dead-code, and duplicate statistics by top-level
directory and writes a ``modules.json`` index to ``.repograph/meta/``.

This powers the ``repograph modules`` CLI command and the module-index
section of ``AGENT_GUIDE.md``.  A single ``repograph modules`` call gives an
AI agent a full structural map of the repository without needing to call
``node`` on every file individually.

Output schema (``modules.json``)
---------------------------------
.. code-block:: json

    [
      {
        "path": "src/advisor",
        "display": "src/advisor/",
        "prod_file_count": 14,
        "test_file_count": 6,
        "total_file_count": 20,
        "file_count": 14,
        "function_count": 87,
        "test_function_count": 12,
        "class_count": 12,
        "key_classes": ["AdvisorEngine", "ShieldGate", "ConsensusEngine"],
        "summary": "Monster Advisor decision engine and consensus layer.",
        "has_tests": true,
        "dead_code_count": 1,
        "duplicate_count": 1
      },
      ...
    ]

``file_count`` duplicates ``prod_file_count`` for backward compatibility.
"""

import ast
from collections import defaultdict

from repograph.settings import DEFAULT_MODULE_EXPANSION_THRESHOLD as _DEFAULT_MODULE_EXPANSION_THRESHOLD
from repograph.graph_store.store import GraphStore
from repograph.core.plugin_framework import ExporterPlugin, PluginManifest as _Manifest
from repograph.plugins.utils import write_meta_json
from repograph.utils.fs import _is_test_file
from repograph.utils import logging as rg_log
from repograph.utils.path_classifier import classify_path


# Maximum number of key classes to surface per module entry.
_MAX_KEY_CLASSES = 5

# Minimum number of functions a class must have to be considered "key"
# (avoids surfacing tiny dataclasses/enums ahead of real controllers).
_MIN_FUNCTIONS_FOR_KEY = 2


def run(
    store: GraphStore,
    repograph_dir: str,
    module_expansion_threshold: int = _DEFAULT_MODULE_EXPANSION_THRESHOLD,
) -> list[dict]:
    """Build a per-directory module index and persist it to meta/modules.json.

    Args:
        store: open GraphStore for the indexed repository.
        repograph_dir: path to the ``.repograph/`` directory (for output).
        module_expansion_threshold: split a module row when file count exceeds this.

    Returns:
        List of module-index dicts, sorted by path.
    """
    modules = _build_index(store, module_expansion_threshold)
    _write_json(modules, repograph_dir)
    return modules


# ---------------------------------------------------------------------------
# Index construction
# ---------------------------------------------------------------------------

def _build_index(store: GraphStore, threshold: int) -> list[dict]:
    """Aggregate all graph data into a per-directory module map."""

    # ── 1. Collect all files ────────────────────────────────────────────────
    all_files = store.get_all_files()

    module_files = _group_files_with_expansion(all_files, threshold)

    # ── 2. Collect all functions ────────────────────────────────────────────
    all_functions = store.get_all_functions()
    fn_by_file: dict[str, list[dict]] = defaultdict(list)
    for fn in all_functions:
        fn_by_file[fn.get("file_path", "")].append(fn)

    # ── 3. Collect all classes ──────────────────────────────────────────────
    all_classes = store.get_all_classes()
    cls_by_file: dict[str, list[dict]] = defaultdict(list)
    for cls in all_classes:
        cls_by_file[cls.get("file_path", "")].append(cls)

    # ── 4. Dead code counts ─────────────────────────────────────────────────
    dead_fns = store.get_dead_functions(min_tier="probably_dead")
    dead_by_file: dict[str, int] = defaultdict(int)
    for d in dead_fns:
        dead_by_file[d.get("file_path", "")] += 1

    # ── 5. Duplicate counts ─────────────────────────────────────────────────
    dup_count_by_file: dict[str, int] = defaultdict(int)
    try:
        dups = store.get_all_duplicate_symbols()
        for dup in dups:
            for fp in (dup.get("file_paths") or []):
                dup_count_by_file[fp] += 1
    except Exception as exc:
        rg_log.warn_once(f"modules_exporter: failed loading duplicate symbols: {exc}")

    # ── 6. Build per-module records ─────────────────────────────────────────
    modules: list[dict] = []
    for module_dir, files in sorted(module_files.items()):
        prod_files = [f for f in files if not _is_test_file(f["path"])]
        test_files = [f for f in files if _is_test_file(f["path"])]
        prod_file_count = len(prod_files)
        test_file_count = len(test_files)
        total_file_count = prod_file_count + test_file_count
        test_function_count = sum(
            len(fn_by_file[f["path"]]) for f in test_files
        )

        # Function and class counts (production files only)
        total_fns = sum(len(fn_by_file[f["path"]]) for f in prod_files)
        all_cls_in_module = [
            cls
            for f in prod_files
            for cls in cls_by_file[f["path"]]
        ]

        # Key classes: those with the most methods, capped at _MAX_KEY_CLASSES
        cls_fn_counts: list[tuple[str, int]] = []
        for cls in all_cls_in_module:
            # Count functions whose qualified_name starts with ClassName.
            cls_name = cls.get("name", "")
            fp = cls.get("file_path", "")
            method_count = sum(
                1 for fn in fn_by_file[fp]
                if (fn.get("qualified_name") or "").startswith(f"{cls_name}.")
            )
            if method_count >= _MIN_FUNCTIONS_FOR_KEY:
                cls_fn_counts.append((cls_name, method_count))
        cls_fn_counts.sort(key=lambda x: -x[1])
        key_classes = [name for name, _ in cls_fn_counts[:_MAX_KEY_CLASSES]]

        # Fallback: if no class has enough methods, just list by name
        if not key_classes and all_cls_in_module:
            key_classes = [
                cls.get("name", "") for cls in all_cls_in_module[:_MAX_KEY_CLASSES]
                if cls.get("name")
            ]

        # Aggregate dead code and duplicate counts
        dead_count = sum(dead_by_file[f["path"]] for f in prod_files)
        dup_count = sum(dup_count_by_file[f["path"]] for f in prod_files)

        # Display path: "src/advisor/" or "__root__" → "(repo root)"
        if module_dir == "__root__":
            display = "(repo root)"
        else:
            display = f"{module_dir}/"

        depth, parent = _module_depth_and_parent(module_dir)
        probe = f"{module_dir}/x.py" if module_dir != "__root__" else "x.py"
        category = (
            "tooling"
            if module_dir != "__root__" and classify_path(probe) != "production"
            else "production"
        )
        summary = _extract_module_summary(
            module_dir,
            prod_files,
            fn_by_file=fn_by_file,
            cls_by_file=cls_by_file,
            key_classes=key_classes,
            total_functions=total_fns,
            class_count=len(all_cls_in_module),
            dead_count=dead_count,
            duplicate_count=dup_count,
            category=category,
        )
        modules.append({
            "path": module_dir,
            "display": display,
            "depth": depth,
            "parent": parent,
            "category": category,
            "prod_file_count": prod_file_count,
            "test_file_count": test_file_count,
            "total_file_count": total_file_count,
            "file_count": prod_file_count,
            "function_count": total_fns,
            "test_function_count": test_function_count,
            "class_count": len(all_cls_in_module),
            "key_classes": key_classes,
            "summary": summary,
            "has_tests": test_file_count > 0,
            "dead_code_count": dead_count,
            "duplicate_count": dup_count,
        })

    return modules


_MAX_MODULE_DEPTH = 3


def _key_at_depth(file_path: str, depth: int) -> str:
    """Directory prefix with ``depth`` segments (parent dir of file)."""
    parts = file_path.replace("\\", "/").split("/")
    if len(parts) == 1:
        return "__root__"
    dir_parts = parts[:-1]
    if not dir_parts:
        return "__root__"
    take = min(depth, len(dir_parts))
    return "/".join(dir_parts[:take])


def _group_files_with_expansion(
    all_files: list[dict],
    threshold: int,
) -> dict[str, list[dict]]:
    """Group files by module directory; expand crowded groups up to ``_MAX_MODULE_DEPTH``."""
    if not all_files:
        return {}
    groups: dict[str, list[dict]] = defaultdict(list)
    for f in all_files:
        groups[_key_at_depth(f["path"], 1)].append(f)

    depth = 1
    while depth < _MAX_MODULE_DEPTH:
        oversized = [
            k for k, fs in groups.items()
            if k != "__root__" and len(fs) > threshold
        ]
        if not oversized:
            break
        new_groups: dict[str, list[dict]] = defaultdict(list)
        for k, fs in groups.items():
            if k in oversized:
                for f in fs:
                    new_groups[_key_at_depth(f["path"], depth + 1)].append(f)
            else:
                new_groups[k].extend(fs)
        groups = new_groups
        depth += 1

    return dict(groups)


def _module_depth_and_parent(module_dir: str) -> tuple[int, str | None]:
    if module_dir == "__root__":
        return 0, None
    parts = module_dir.split("/")
    depth = len(parts)
    parent = "/".join(parts[:-1]) if depth > 1 else None
    return depth, parent


def _extract_module_summary(
    module_dir: str,
    prod_files: list[dict],
    *,
    fn_by_file: dict[str, list[dict]] | None = None,
    cls_by_file: dict[str, list[dict]] | None = None,
    key_classes: list[str] | None = None,
    total_functions: int = 0,
    class_count: int = 0,
    dead_count: int = 0,
    duplicate_count: int = 0,
    category: str = "production",
) -> str:
    """Return a one-line summary for the module using progressively weaker evidence."""
    if module_dir == "__root__":
        return ""

    init_path_candidates = [
        f.get("abs_path", "") for f in prod_files
        if f["path"].endswith("__init__.py")
    ]
    for abs_path in init_path_candidates:
        doc = _read_python_module_docstring(abs_path)
        if doc:
            return _first_sentence(doc)

    candidate_files = _summary_candidate_files(
        prod_files,
        fn_by_file=fn_by_file,
        cls_by_file=cls_by_file,
    )
    for file_entry in candidate_files:
        doc = _read_python_module_docstring(file_entry.get("abs_path", ""))
        if doc:
            return _first_sentence(doc)

    for file_entry in candidate_files:
        class_doc = _read_first_class_docstring(file_entry.get("abs_path", ""))
        if class_doc:
            return _first_sentence(class_doc)

    return _heuristic_module_summary(
        prod_files,
        key_classes=key_classes or [],
        total_functions=total_functions,
        class_count=class_count,
        dead_count=dead_count,
        duplicate_count=duplicate_count,
        category=category,
    )


def _summary_candidate_files(
    prod_files: list[dict],
    *,
    fn_by_file: dict[str, list[dict]] | None = None,
    cls_by_file: dict[str, list[dict]] | None = None,
) -> list[dict]:
    """Return non-``__init__`` production files ordered by likely summary usefulness."""
    fn_by_file = fn_by_file or {}
    cls_by_file = cls_by_file or {}

    def _rank(file_entry: dict) -> tuple[int, int, int, str]:
        path = file_entry.get("path", "")
        fn_count = len(fn_by_file.get(path, []))
        cls_count = len(cls_by_file.get(path, []))
        line_count = int(file_entry.get("line_count") or 0)
        return (-fn_count, -cls_count, -line_count, path)

    return sorted(
        [
            file_entry
            for file_entry in prod_files
            if not (file_entry.get("path", "") or "").endswith("__init__.py")
        ],
        key=_rank,
    )


def _read_python_module_docstring(abs_path: str) -> str:
    if not abs_path:
        return ""
    try:
        with open(abs_path, encoding="utf-8", errors="replace") as fh:
            source = fh.read()
        module = ast.parse(source)
    except (OSError, SyntaxError):
        return ""
    doc = ast.get_docstring(module)
    return doc.strip() if doc else ""


def _read_first_class_docstring(abs_path: str) -> str:
    if not abs_path:
        return ""
    try:
        with open(abs_path, encoding="utf-8", errors="replace") as fh:
            source = fh.read()
        module = ast.parse(source)
    except (OSError, SyntaxError):
        return ""

    for node in module.body:
        if isinstance(node, ast.ClassDef):
            doc = ast.get_docstring(node)
            if doc:
                return doc.strip()
    return ""


def _first_sentence(text: str) -> str:
    """Return the first sentence of a docstring, capped at 120 chars."""
    text = text.strip()
    # Split on first period followed by whitespace or end-of-string
    for i, ch in enumerate(text):
        if ch == "." and (i + 1 >= len(text) or text[i + 1] in (" ", "\n", "\r")):
            return text[: i + 1][:120]
    # No sentence-ending period — return the first line capped at 120 chars
    first_line = text.split("\n")[0].strip()
    return first_line[:120]


def _heuristic_module_summary(
    prod_files: list[dict],
    *,
    key_classes: list[str],
    total_functions: int,
    class_count: int,
    dead_count: int,
    duplicate_count: int,
    category: str,
) -> str:
    """Return a compact structural fallback when docstring evidence is absent."""
    if not prod_files:
        return ""

    parts = [
        (
            f"{'Tooling' if category == 'tooling' else 'Production'} module with "
            f"{len(prod_files)} file{'s' if len(prod_files) != 1 else ''}"
        )
    ]
    activity: list[str] = []
    if total_functions:
        activity.append(f"{total_functions} function{'s' if total_functions != 1 else ''}")
    if class_count:
        activity.append(f"{class_count} class{'es' if class_count != 1 else ''}")
    if activity:
        parts[0] += " containing " + " and ".join(activity)
    parts[0] += "."

    if key_classes:
        shown = ", ".join(key_classes[:2])
        suffix = "..." if len(key_classes) > 2 else ""
        parts.append(f"Key classes: {shown}{suffix}.")

    issues: list[str] = []
    if dead_count:
        issues.append(f"{dead_count} dead-code signal{'s' if dead_count != 1 else ''}")
    if duplicate_count:
        issues.append(f"{duplicate_count} duplicate signal{'s' if duplicate_count != 1 else ''}")
    if issues:
        parts.append("Includes " + " and ".join(issues) + ".")

    return " ".join(parts)[:220]


def _write_json(payload, repograph_dir: str) -> None:
    """Persist JSON artefact to .repograph/meta/."""
    write_meta_json(repograph_dir, "modules.json", payload)


class ModulesExporterPlugin(ExporterPlugin):
    manifest = _Manifest(
        id="exporter.modules",
        name="Module exporter",
        kind="exporter",
        description="Writes modules artefact to .repograph/meta/.",
        requires=("module_index",),
        produces=("artifacts.modules_json",),
        hooks=("on_export",),
        order=100,
    )

    def export(self, store=None, repograph_dir: str = "", config=None, **kwargs):
        if store is None:
            return {}
        return {"kind": "modules", "written": True, "result": run(store, repograph_dir)}


def build_plugin() -> ModulesExporterPlugin:
    return ModulesExporterPlugin()
