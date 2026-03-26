#!/usr/bin/env python3
"""Scan repograph/plugins for plugin.py packages; compare to discovery ORDER tuples.

Exit 0 if every discovered subpackage is listed in discovery.py; exit 1 otherwise.
Run from repo root: python scripts/check_plugin_coverage.py
"""
from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from repograph.plugins import discovery as d  # noqa: E402

# Subpackages with plugin.py that are not registered via discovery (helpers, tracers-only, …).
_SKIP: frozenset[tuple[str, str]] = frozenset({
    ("static_analyzers", "interface_map"),  # no build_plugin; API helpers only
    ("dynamic_analyzers", "coverage_tracer"),  # registered as tracer, not dynamic_analyzer
})


def _plugin_subdirs(kind: str) -> set[str]:
    base = os.path.join(REPO_ROOT, "repograph", "plugins", kind)
    out: set[str] = set()
    if not os.path.isdir(base):
        return out
    for name in os.listdir(base):
        p = os.path.join(base, name)
        if not os.path.isdir(p) or name.startswith("_") or name in ("__pycache__",):
            continue
        if os.path.isfile(os.path.join(p, "plugin.py")) and (kind, name) not in _SKIP:
            out.add(name)
    return out


def main() -> int:
    orders = {
        "parsers": d.PARSER_ORDER,
        "static_analyzers": d.STATIC_ANALYZER_ORDER,
        "framework_adapters": d.FRAMEWORK_ADAPTER_ORDER,
        "demand_analyzers": d.DEMAND_ANALYZER_ORDER,
        "exporters": d.EXPORTER_ORDER,
        "evidence_producers": d.EVIDENCE_PRODUCER_ORDER,
        "dynamic_analyzers": d.DYNAMIC_ANALYZER_ORDER,
    }
    failures: list[str] = []
    for kind, order in orders.items():
        on_disk = _plugin_subdirs(kind)
        listed = set(order)
        missing = sorted(on_disk - listed)
        if missing:
            failures.append(f"{kind}: on-disk plugin.py dirs not in discovery ORDER: {missing}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
