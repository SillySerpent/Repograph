from __future__ import annotations

from repograph.core.plugin_framework import FrameworkAdapterPlugin, PluginManifest

_DECORATOR_HTTP_METHOD: dict[str, str] = {
    ".get": "GET",
    ".post": "POST",
    ".put": "PUT",
    ".patch": "PATCH",
    ".delete": "DELETE",
    ".websocket": "WEBSOCKET",
}


class FastAPIFrameworkAdapterPlugin(FrameworkAdapterPlugin):
    manifest = PluginManifest(
        id="framework.fastapi",
        name="FastAPI framework adapter",
        kind="framework_adapter",
        description="Annotates parsed Python files with FastAPI router/framework hints.",
        requires=("symbols", "imports"),
        produces=("frameworks.fastapi",),
        languages=("python",),
        frameworks=("fastapi",),
        hooks=("on_file_parsed",),
    )

    def inspect(self, **kwargs):
        file_record = kwargs.get("file_record")
        parsed_file = kwargs.get("parsed_file")
        if file_record is None or parsed_file is None or file_record.language != "python":
            return {}

        imports = {imp.module_path for imp in parsed_file.imports}
        route_functions = []
        for fn in parsed_file.functions:
            decorators = fn.decorators or []
            for dec in decorators:
                for suffix, method in _DECORATOR_HTTP_METHOD.items():
                    if dec.endswith(suffix):
                        route_functions.append({
                            "qualified_name": fn.qualified_name,
                            "http_method": fn.http_method or method,
                            "route_path": fn.route_path,
                        })
                        break

        detected = bool(route_functions) or any(mod.startswith("fastapi") for mod in imports)
        if not detected:
            return {}
        return {
            "frameworks": ["fastapi"],
            "route_functions": route_functions,
            "page_components": [],
            "server_actions": [],
            "import_modules": sorted(mod for mod in imports if mod.startswith("fastapi")),
        }


def build_plugin() -> FastAPIFrameworkAdapterPlugin:
    return FastAPIFrameworkAdapterPlugin()
