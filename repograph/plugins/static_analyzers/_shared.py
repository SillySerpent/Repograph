from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable, Any

from repograph.plugins.utils import parse_file_with_plugins

_PY_FROM_RE = re.compile(r"^\s*from\s+([a-zA-Z0-9_./]+)\s+import\b", re.MULTILINE)
_PY_IMPORT_RE = re.compile(r"^\s*import\s+([a-zA-Z0-9_., ]+)$", re.MULTILINE)
_JS_FROM_RE = re.compile(r"from\s+['\"]([^'\"]+)['\"]")
_JS_REQUIRE_RE = re.compile(r"require\(['\"]([^'\"]+)['\"]\)")
_DB_IMPORT_PATTERNS = (
    re.compile(r"\bimport\s+sqlite3\b"),
    re.compile(r"\bfrom\s+sqlalchemy\b"),
    re.compile(r"\bimport\s+sqlalchemy\b"),
    re.compile(r"\bimport\s+psycopg2\b"),
    re.compile(r"\bimport\s+aiosqlite\b"),
    re.compile(r"\bfrom\s+motor\b"),
    re.compile(r"\bfrom\s+pymongo\b"),
    re.compile(r"\brequire\(['\"]pg['\"]\)"),
    re.compile(r"\brequire\(['\"]mysql2?['\"]\)"),
    re.compile(r"\bfrom ['\"]pg['\"]"),
    re.compile(r"\bfrom ['\"]mysql2?['\"]"),
)

def iter_code_files(service: Any, repo_path: Path) -> Iterable[tuple[str, str, Path]]:
    for file_entry in service.get_all_files() if service is not None else []:
        rel = file_entry.get("path", "")
        ext = Path(rel).suffix.lower()
        if ext not in {".py", ".js", ".jsx", ".ts", ".tsx"}:
            continue
        full = repo_path / rel
        if not full.is_file():
            continue
        yield rel, full.read_text(encoding="utf-8", errors="ignore"), full


def extract_imports(text: str) -> list[str]:
    found: list[str] = []
    found.extend(m.group(1).strip() for m in _PY_FROM_RE.finditer(text))
    for m in _PY_IMPORT_RE.finditer(text):
        found.extend(part.strip() for part in m.group(1).split(',') if part.strip())
    found.extend(m.group(1).strip() for m in _JS_FROM_RE.finditer(text))
    found.extend(m.group(1).strip() for m in _JS_REQUIRE_RE.finditer(text))
    return [f for f in found if f and not f.startswith('.')]


def looks_db_bound(text: str) -> bool:
    return any(pattern.search(text) for pattern in _DB_IMPORT_PATTERNS)


def parsed_framework_context(repo_path: Path, rel: str, text: str) -> tuple[list[str], list[str]]:
    parsed = parse_file_with_plugins(repo_path, rel, text=text)
    frameworks = sorted(set(getattr(parsed, "framework_hints", []) or [])) if parsed is not None else []
    route_functions: list[str] = []
    if parsed is not None:
        for result in getattr(parsed, "plugin_artifacts", {}).values():
            if isinstance(result, dict):
                route_functions.extend(result.get("route_functions", []) or [])
    if not route_functions and ("@app.route" in text or ".route(" in text or "@router." in text):
        route_functions = ["<textual_route_hint>"]
    return frameworks, sorted(set(route_functions))
