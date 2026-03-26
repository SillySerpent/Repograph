from __future__ import annotations

"""Invariants exporter plugin — all logic lives here. Fires on: on_export."""

"""Phase 18 — Invariant Extraction: architectural constraints from docstrings.

Scans function and class docstrings for documented invariants — constraints,
guarantees, and thread-safety notes that the codebase explicitly states must
always hold.  These are stored as ``Invariant`` nodes so the ``repograph
invariants`` command can surface them and AGENT_GUIDE.md can warn AI agents
before they accidentally violate them.

Pattern examples that are captured
------------------------------------
- ``INV-02: NEVER calls RiskEngine.evaluate()``
- ``INVARIANT: this function is not reentrant``
- ``CONTRACT: always called with the GIL held``
- ``GUARANTEE: return value is never None``
- ``NEVER mutates shared state``
- ``MUST NOT be called from the event loop``
- ``NOT thread-safe``
- ``Thread-safe: yes``

Output
------
Invariants are written to ``.repograph/meta/invariants.json`` and also stored
as ``Invariant`` nodes in the graph for queryability.
"""

import os
import re
from dataclasses import dataclass, field

from repograph.graph_store.store import GraphStore
from repograph.core.plugin_framework import ExporterPlugin, PluginManifest as _Manifest
from repograph.plugins.utils import write_meta_json
from repograph.utils import logging as rg_log


# ---------------------------------------------------------------------------
# Invariant patterns
# ---------------------------------------------------------------------------

@dataclass
class Invariant:
    """A single documented invariant on a symbol."""
    symbol_id: str
    symbol_name: str
    symbol_type: str        # "function" | "class"
    file_path: str
    invariant_text: str
    invariant_type: str     # "constraint" | "guarantee" | "thread" | "lifecycle"
    line_hint: int = 0


# Ordered patterns — first match wins for type classification
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Explicit INV-N / INVARIANT / CONTRACT labels — label at start of sentence
    ("constraint", re.compile(
        r"(?:INV-\d+\s*:?\s*|INVARIANT\s*:?\s*|CONTRACT\s*:?\s*)"
        r"(.{10,200})",
        re.I,
    )),
    # Inline INV-N reference: "... never returns None (INV-05)" — capture whole sentence
    ("constraint", re.compile(
        r"([^.\n]{10,180}\(INV-\d+\)[^.\n]{0,40})",
    )),
    # GUARANTEE / ENSURES
    ("guarantee", re.compile(
        r"(?:GUARANTEE\s*:?\s*|ENSURES\s*:?\s*|POSTCONDITION\s*:?\s*)"
        r"(.{10,200})",
        re.I,
    )),
    # Thread-safety statements
    ("thread", re.compile(
        r"((?:NOT\s+)?thread[- ]safe[^.\n]{0,120}|"
        r"NOT\s+reentrant[^.\n]{0,80}|"
        r"reentrant\s*:\s*\w+[^.\n]{0,60})",
        re.I,
    )),
    # NEVER / MUST NOT / DO NOT — strong constraint (case-insensitive, mid-sentence too)
    ("constraint", re.compile(
        r"([^.\n]{0,60}(?:Never|NEVER)\s+[a-z][^.\n]{5,120}|"
        r"MUST\s+NOT\s+[A-Za-z][^.\n]{5,150}|"
        r"DO\s+NOT\s+[A-Za-z][^.\n]{5,150})",
    )),
    # ALWAYS / MUST — guarantee language
    ("guarantee", re.compile(
        r"(ALWAYS\s+[A-Za-z][^.\n]{5,150}|"
        r"MUST\s+(?!NOT)[A-Za-z][^.\n]{5,150})",
    )),
    # Lifecycle ordering constraints
    ("lifecycle", re.compile(
        r"(Must\s+be\s+(?:started|stopped|called|initialised?|initialized?)"
        r"[^.\n]{5,150})",
        re.I,
    )),
]

_MIN_TEXT_LEN = 10
_MAX_TEXT_LEN = 200
_MIN_WORDS = 12

# Docstrings that describe the invariant extractor rather than stating a constraint.
_META_SUBSTRINGS = (
    "invariant_type",
    "invariant_text",
    "extracted by phase",
    "phase 18",
    "typer.option",
    "typer.argument",
    "argparse",
    "add_argument",
    "rich.console",
    "click.command",
    "--help",
    "usage:",
    "[default:",
)

# CLI / help prose (Typer, argparse, Rich) — not architectural invariants.
_CLI_HELPISH_RE = re.compile(
    r"(?:typer\.|argparse\.|add_argument|rich\.|click\.(?:command|option)|\s--[\w-]{2,})",
    re.I,
)

# Quoted meta-words in prose (explaining patterns, not declaring rules).
_QUOTED_META_RE = re.compile(
    r"['\"](constraint|guarantee|thread|lifecycle)['\"]",
    re.I,
)

# Short standalone rules: NEVER/MUST/NOT thread-safe / Thread-safe:
_SHORT_INVARIANT_OK_RE = re.compile(
    r"^(?:NEVER|MUST\s+NOT|DO\s+NOT|MUST\s+|NOT\s+thread-safe|Thread-safe:)"
    r"|^(?:Never|Must not|Do not)\s",
    re.I | re.M,
)


def run(store: GraphStore, repograph_dir: str) -> list[dict]:
    """Scan all docstrings and extract documented invariants.

    Args:
        store: open GraphStore for the indexed repository.
        repograph_dir: path to the ``.repograph/`` directory.

    Returns:
        List of invariant dicts (also written to meta/invariants.json).
    """
    invariants = _extract_all(store)
    serialised = [_to_dict(inv) for inv in invariants]
    _write_json(serialised, repograph_dir)
    return serialised


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _extract_all(store: GraphStore) -> list[Invariant]:
    """Extract invariants from all function and class docstrings."""
    results: list[Invariant] = []

    # Functions — query docstrings directly (get_all_functions() omits them for speed)
    try:
        rows = store.query(
            """
            MATCH (f:Function)
            WHERE f.docstring IS NOT NULL AND f.docstring <> ''
            RETURN f.id, f.qualified_name, f.name, f.file_path, f.docstring
            """
        )
        for fn_id, qname, name, fp, doc in rows:
            if not doc:
                continue
            for inv in _scan_docstring(doc):
                results.append(Invariant(
                    symbol_id=fn_id or "",
                    symbol_name=qname or name or "",
                    symbol_type="function",
                    file_path=fp or "",
                    invariant_text=inv[1],
                    invariant_type=inv[0],
                ))
    except Exception as exc:
        rg_log.warn_once(f"invariants: failed scanning function docstrings: {exc}")

    # Classes — query docstrings directly
    try:
        rows = store.query(
            """
            MATCH (c:Class)
            WHERE c.docstring IS NOT NULL AND c.docstring <> ''
            RETURN c.id, c.qualified_name, c.name, c.file_path, c.docstring
            """
        )
        for cls_id, qname, name, fp, doc in rows:
            if not doc:
                continue
            for inv in _scan_docstring(doc):
                results.append(Invariant(
                    symbol_id=cls_id or "",
                    symbol_name=qname or name or "",
                    symbol_type="class",
                    file_path=fp or "",
                    invariant_text=inv[1],
                    invariant_type=inv[0],
                ))
    except Exception as exc:
        rg_log.warn_once(f"invariants: failed scanning class docstrings: {exc}")

    # Deduplicate by (symbol_id, invariant_text) to avoid double-counting
    seen: set[tuple[str, str]] = set()
    unique: list[Invariant] = []
    for inv in results:
        key = (inv.symbol_id, inv.invariant_text[:80])
        if key not in seen:
            seen.add(key)
            unique.append(inv)

    return unique


def _scan_docstring(docstring: str) -> list[tuple[str, str]]:
    """Return list of (invariant_type, invariant_text) from a docstring."""
    found: list[tuple[str, str]] = []
    seen_texts: set[str] = set()
    for inv_type, pattern in _PATTERNS:
        for m in pattern.finditer(docstring):
            text = m.group(1).strip() if m.lastindex else m.group(0).strip()
            # Normalise whitespace
            text = re.sub(r"\s+", " ", text)
            if len(text) < _MIN_TEXT_LEN or len(text) > _MAX_TEXT_LEN:
                continue
            if _is_meta_invariant_text(text):
                continue
            # Deduplicate within this docstring
            key = text[:60].lower()
            if key in seen_texts:
                continue
            seen_texts.add(key)
            found.append((inv_type, text))
    return found


def _looks_like_cli_help_prose(text: str) -> bool:
    """True when text looks like CLI option/help documentation, not a code contract."""
    if _CLI_HELPISH_RE.search(text):
        return True
    low = text.lower()
    if "show this message" in low and "exit" in low:
        return True
    if "same as " in low and "--" in text:
        return True
    return False


def _is_meta_invariant_text(text: str) -> bool:
    """True when ``text`` is meta-documentation about invariants, not a real rule."""
    low = text.lower()
    for sub in _META_SUBSTRINGS:
        if sub in low:
            return True
    if _QUOTED_META_RE.search(text):
        return True
    if _looks_like_cli_help_prose(text):
        return True
    wc = len(text.split())
    if wc < _MIN_WORDS:
        # Allow short imperative invariants (e.g. ``Never raises``).
        if _SHORT_INVARIANT_OK_RE.match(text.strip()):
            return False
        return True
    # Mid-sentence fragments (audit trail / doc generation noise)
    if text.strip().endswith(".") and low.startswith(("s ", "s extracted", "are extracted")):
        return True
    return False


def _to_dict(inv: Invariant) -> dict:
    return {
        "symbol_id": inv.symbol_id,
        "symbol_name": inv.symbol_name,
        "symbol_type": inv.symbol_type,
        "file_path": inv.file_path,
        "invariant_text": inv.invariant_text,
        "invariant_type": inv.invariant_type,
    }


def _write_json(payload, repograph_dir: str) -> None:
    """Persist JSON artefact to .repograph/meta/."""
    write_meta_json(repograph_dir, "invariants.json", payload)


class InvariantsExporterPlugin(ExporterPlugin):
    manifest = _Manifest(
        id="exporter.invariants",
        name="Invariants exporter",
        kind="exporter",
        description="Writes invariants artefact to .repograph/meta/.",
        requires=("meta.invariants",),
        produces=("artifacts.invariants_json",),
        hooks=("on_export",),
        order=130,
    )

    def export(self, store=None, repograph_dir: str = "", config=None, **kwargs):
        if store is None:
            return {}
        return {"kind": "invariants", "written": True, "result": run(store, repograph_dir)}


def build_plugin() -> InvariantsExporterPlugin:
    return InvariantsExporterPlugin()
