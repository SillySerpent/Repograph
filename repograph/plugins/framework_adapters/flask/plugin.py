from __future__ import annotations

from repograph.core.plugin_framework import FrameworkAdapterPlugin, PluginManifest

_HTTP_DECORATOR_SUFFIXES = {"route"}


class FlaskFrameworkAdapterPlugin(FrameworkAdapterPlugin):
    manifest = PluginManifest(
        id="framework.flask",
        name="Flask framework adapter",
        kind="framework_adapter",
        description="Annotates parsed Python files with Flask route/framework hints.",
        requires=("symbols", "imports"),
        produces=("frameworks.flask",),
        languages=("python",),
        frameworks=("flask",),
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
            if any(dec == "app.route" or dec.endswith(".route") or dec == "route" for dec in decorators):
                route_functions.append(fn.qualified_name)

        detected = bool(route_functions) or any(mod.startswith("flask") for mod in imports)
        if not detected:
            return {}
        return {
            "frameworks": ["flask"],
            "route_functions": route_functions,
            "import_modules": sorted(mod for mod in imports if mod.startswith("flask")),
        }


def build_plugin() -> FlaskFrameworkAdapterPlugin:
    return FlaskFrameworkAdapterPlugin()
