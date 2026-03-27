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
        app_route = '/app/' in f'/{rel}'
        page = rel.endswith('/page.tsx') or rel.endswith('/page.jsx')
        layout = rel.endswith('/layout.tsx') or rel.endswith('/layout.jsx')
        route = rel.endswith('/route.ts') or rel.endswith('/route.js')

        # Infer route_path from file path for Next.js app router convention.
        route_path = ""
        if route:
            parts = rel
            if parts.startswith("app/"):
                parts = parts[4:]
            for suffix in ("/route.ts", "/route.js", "route.ts", "route.js"):
                if parts.endswith(suffix):
                    parts = parts[: -len(suffix)]
                    break
            route_path = "/" + parts.strip("/") if parts.strip("/") else "/"

        # Each exported HTTP method function (GET, POST, etc.) is a route handler.
        route_functions = [
            {
                "qualified_name": m.group(2),
                "http_method": m.group(2),
                "route_path": route_path,
            }
            for m in _ROUTE_RE.finditer(text)
        ]

        # Page components are inferred from file path; no qualified name available here.
        page_components: list[str] = []
        if page or layout:
            # Use the file path as a proxy identifier for the component.
            page_components.append(rel)

        server_actions_detected = bool(_SERVER_ACTION_RE.search(text))
        detected = (
            any(mod.startswith("next") or mod == "next" for mod in imports)
            or app_route or page or layout or route
            or bool(route_functions) or server_actions_detected
        )
        if not detected:
            return {}
        return {
            "frameworks": ["nextjs"],
            "route_functions": route_functions,
            "page_components": page_components,
            "server_actions": [],
            "app_router": app_route,
            "import_modules": sorted(mod for mod in imports if mod.startswith("next")),
        }


def build_plugin() -> NextJsFrameworkAdapterPlugin:
    return NextJsFrameworkAdapterPlugin()
