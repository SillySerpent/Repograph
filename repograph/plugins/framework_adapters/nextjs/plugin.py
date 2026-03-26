from __future__ import annotations

import re

from repograph.core.plugin_framework import FrameworkAdapterPlugin, PluginManifest

_ROUTE_RE = re.compile(r"export\s+(async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b")
_SERVER_ACTION_RE = re.compile(r"'use server'|\"use server\"")


class NextJsFrameworkAdapterPlugin(FrameworkAdapterPlugin):
    manifest = PluginManifest(
        id="framework.nextjs",
        name="Next.js framework adapter",
        kind="framework_adapter",
        description="Annotates JS/TS files with Next.js page/layout/route/server-action hints.",
        requires=("symbols",),
        produces=("frameworks.nextjs",),
        languages=("javascript", "typescript"),
        frameworks=("nextjs",),
        hooks=("on_file_parsed",),
    )

    def inspect(self, **kwargs):
        file_record = kwargs.get("file_record")
        parsed_file = kwargs.get("parsed_file")
        text = kwargs.get("text") or ""
        if file_record is None or parsed_file is None or file_record.language not in {"javascript", "typescript"}:
            return {}
        imports = {imp.module_path for imp in parsed_file.imports}
        rel = getattr(file_record, 'path', '').replace('\\', '/')
        route_handlers = [m.group(2) for m in _ROUTE_RE.finditer(text)]
        app_route = '/app/' in f'/{rel}'
        page = rel.endswith('/page.tsx') or rel.endswith('/page.jsx')
        layout = rel.endswith('/layout.tsx') or rel.endswith('/layout.jsx')
        route = rel.endswith('/route.ts') or rel.endswith('/route.js')
        detected = (
            any(mod.startswith("next") or mod == "next" for mod in imports)
            or app_route or page or layout or route or bool(route_handlers) or bool(_SERVER_ACTION_RE.search(text))
        )
        if not detected:
            return {}
        return {
            "frameworks": ["nextjs"],
            "page_component": page,
            "layout_component": layout,
            "route_handlers": sorted(set(route_handlers)),
            "server_action": bool(_SERVER_ACTION_RE.search(text)),
            "app_router": app_route,
            "import_modules": sorted(mod for mod in imports if mod.startswith("next")),
        }


def build_plugin() -> NextJsFrameworkAdapterPlugin:
    return NextJsFrameworkAdapterPlugin()
