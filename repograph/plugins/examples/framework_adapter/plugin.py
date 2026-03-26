"""REFERENCE ONLY — not registered in production.

How to implement a framework adapter plugin
-------------------------------------------
1. Subclass ``FrameworkAdapterPlugin``.
2. Set ``kind="framework_adapter"``, ``languages``, optional ``frameworks``.
3. Declare ``hooks=("on_file_parsed",)``. The scheduler invokes ``inspect`` with
   ``file_record``, ``parsed_file``, and other kwargs after the parser ran.
4. Return a dict; common keys include ``frameworks: list[str]`` and
   ``route_functions``. Empty dict means “no signal”.
5. Register: append subpackage name to ``FRAMEWORK_ADAPTER_ORDER`` in ``discovery.py``.

See ``plugins/framework_adapters/flask/plugin.py`` for a full implementation.
"""
from __future__ import annotations

from typing import Any

from repograph.core.plugin_framework import FrameworkAdapterPlugin, PluginManifest


class ExampleFrameworkAdapterPlugin(FrameworkAdapterPlugin):
    manifest = PluginManifest(
        id="framework_adapter.example_reference",
        name="Example framework adapter (reference)",
        kind="framework_adapter",
        description="Reference stub — not used in production.",
        requires=("symbols", "imports"),
        produces=("frameworks.example",),
        languages=("python",),
        frameworks=("example",),
        hooks=("on_file_parsed",),
    )

    def inspect(self, **kwargs: Any) -> dict[str, Any]:
        return {}


def build_plugin() -> ExampleFrameworkAdapterPlugin:
    return ExampleFrameworkAdapterPlugin()
