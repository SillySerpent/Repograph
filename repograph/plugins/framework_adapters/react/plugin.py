from __future__ import annotations

import re

from repograph.core.plugin_framework import FrameworkAdapterPlugin, PluginManifest

_CLIENT_HOOKS = ("useState(", "useEffect(", "useMemo(", "useCallback(", "useReducer(")
_COMPONENT_RE = re.compile(r"export\s+default\s+function\s+([A-Z][A-Za-z0-9_]*)|function\s+([A-Z][A-Za-z0-9_]*)\s*\(")
_HOOK_RE = re.compile(r"function\s+(use[A-Z][A-Za-z0-9_]*)\s*\(")


class ReactFrameworkAdapterPlugin(FrameworkAdapterPlugin):
    manifest = PluginManifest(
        id="framework.react",
        name="React framework adapter",
        kind="framework_adapter",
        description="Annotates parsed JS/TS files with React component and hook hints.",
        requires=("symbols",),
        produces=("frameworks.react",),
        languages=("javascript", "typescript"),
        frameworks=("react",),
        hooks=("on_file_parsed",),
    )

    def inspect(self, **kwargs):
        file_record = kwargs.get("file_record")
        parsed_file = kwargs.get("parsed_file")
        text = kwargs.get("text") or ""
        if file_record is None or parsed_file is None or file_record.language not in {"javascript", "typescript"}:
            return {}
        imports = {imp.module_path for imp in parsed_file.imports}
        rel = getattr(file_record, 'path', '')
        component_names: list[str] = []
        for m in _COMPONENT_RE.finditer(text):
            name = m.group(1) or m.group(2)
            if name:
                component_names.append(name)
        hook_names = [m.group(1) for m in _HOOK_RE.finditer(text)]
        detected = (
            any(mod in {"react", "react/jsx-runtime"} or mod.startswith("react/") for mod in imports)
            or any(token in text for token in _CLIENT_HOOKS)
            or rel.endswith((".jsx", ".tsx"))
            or bool(component_names)
        )
        if not detected:
            return {}
        return {
            "frameworks": ["react"],
            "component_names": sorted(set(component_names)),
            "hook_names": sorted(set(hook_names)),
            "client_component": ("'use client'" in text) or ('"use client"' in text),
            "import_modules": sorted(mod for mod in imports if mod.startswith("react")),
        }


def build_plugin() -> ReactFrameworkAdapterPlugin:
    return ReactFrameworkAdapterPlugin()
