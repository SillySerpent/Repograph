from __future__ import annotations

"""Stable evidence taxonomy for RepoGraph producers/consumers.

This module keeps evidence naming predictable as the tool evolves from purely
static indexing toward mixed static/declared/framework/observed evidence.
The taxonomy is intentionally lightweight in Phase 6: features can emit or
consume these normalized keys without forcing a full schema rewrite.
"""

from dataclasses import dataclass

SOURCE_STATIC = "static"
SOURCE_FRAMEWORK = "framework"
SOURCE_DECLARED = "declared"
SOURCE_OBSERVED = "observed"
SOURCE_INFERRED = "inferred"

SOURCES = (
    SOURCE_STATIC,
    SOURCE_FRAMEWORK,
    SOURCE_DECLARED,
    SOURCE_OBSERVED,
    SOURCE_INFERRED,
)

CAP_SYMBOLS = "symbols"
CAP_IMPORTS = "imports"
CAP_CALL_EDGES = "call_edges"
CAP_FRAMEWORK_HINTS = "framework_hints"
CAP_CONFIG_KEYS = "config_keys"
CAP_CONFIG_FLOW = "config_flow"
CAP_DECLARED_DEPENDENCIES = "declared_dependencies"
CAP_RUNTIME_OVERLAY = "runtime_overlay"
CAP_CLASS_ROLES = "class_roles"
CAP_MODULE_COMPONENT_SIGNALS = "module_component_signals"
CAP_DECOMPOSITION_SIGNALS = "decomposition_signals"
CAP_ENTRY_POINTS = "entry_points"
CAP_DOC_WARNINGS = "doc_warnings"

CAP_BOUNDARY_RULES = "boundary_rules"
CAP_ARCH_CONFORMANCE = "architecture_conformance"
CAP_OBSERVED_RUNTIME_FINDINGS = "observed_runtime_findings"
CAP_REPORT_SURFACES = "report_surfaces"

CAPABILITIES = (
    CAP_SYMBOLS,
    CAP_IMPORTS,
    CAP_CALL_EDGES,
    CAP_FRAMEWORK_HINTS,
    CAP_CONFIG_KEYS,
    CAP_CONFIG_FLOW,
    CAP_DECLARED_DEPENDENCIES,
    CAP_RUNTIME_OVERLAY,
    CAP_CLASS_ROLES,
    CAP_MODULE_COMPONENT_SIGNALS,
    CAP_DECOMPOSITION_SIGNALS,
    CAP_ENTRY_POINTS,
    CAP_DOC_WARNINGS,
    CAP_BOUNDARY_RULES,
    CAP_ARCH_CONFORMANCE,
    CAP_OBSERVED_RUNTIME_FINDINGS,
    CAP_REPORT_SURFACES,
)


@dataclass(frozen=True)
class EvidenceTag:
    kind: str
    source: str

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "source": self.source}


def evidence_tag(kind: str, source: str) -> EvidenceTag:
    if source not in SOURCES:
        raise ValueError(f"Unknown evidence source: {source}")
    return EvidenceTag(kind=kind, source=source)
