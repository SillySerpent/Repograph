"""Confidence scoring rules for edges and pathway confidence."""
from __future__ import annotations
import math


# ---------------------------------------------------------------------------
# Edge confidence constants
# ---------------------------------------------------------------------------

CONF_DIRECT_CALL = 1.0       # fully qualified, same-file call
CONF_IMPORT_RESOLVED = 0.9   # call resolved through import table
CONF_METHOD_CALL = 0.7       # obj.method — receiver type inferred
CONF_FUZZY_MATCH = 0.3       # name match only, no import resolution
CONF_DYNAMIC = 0.3           # dynamic dispatch / string-based

CONF_IMPORT_STATIC = 1.0     # file exists in repo
CONF_IMPORT_EXTERNAL = 0.6   # external module (node_modules, stdlib)
CONF_IMPORT_UNRESOLVABLE = 0.0
CONF_INLINE_IMPORT = 0.8     # ``from M import f`` inside a function body (Phase 4)

CONF_HERITAGE_DIRECT = 0.95  # base class found via import resolution
CONF_HERITAGE_FUZZY = 0.5    # base class name matched but not resolved


# ---------------------------------------------------------------------------
# Pathway confidence
# ---------------------------------------------------------------------------

def geometric_mean_confidence(confidences: list[float]) -> float:
    """
    Compute geometric mean of confidence values.
    Returns 0.0 for empty list.
    A pathway's confidence is the geometric mean of all its edge confidences.
    This is more conservative than arithmetic mean and correctly penalises
    any single weak link.
    """
    if not confidences:
        return 0.0
    product = math.prod(max(0.0001, c) for c in confidences)
    return product ** (1.0 / len(confidences))


def path_confidence(call_edges_confidences: list[float]) -> float:
    """Overall pathway confidence from its CALLS edge confidences."""
    return geometric_mean_confidence(call_edges_confidences)


# ---------------------------------------------------------------------------
# Resolution reason → confidence
# ---------------------------------------------------------------------------

REASON_CONFIDENCE: dict[str, float] = {
    "direct_call": CONF_DIRECT_CALL,
    "import_resolved": CONF_IMPORT_RESOLVED,
    "method_call": CONF_METHOD_CALL,
    "dynamic": CONF_DYNAMIC,
    "decorator": CONF_IMPORT_RESOLVED,
    "fuzzy": CONF_FUZZY_MATCH,
    "callback_registration": 0.6,
}


# ---------------------------------------------------------------------------
# Call-edge sanity filter
# ---------------------------------------------------------------------------

def should_skip_call_edge(
    from_function_id: str,
    to_function_id: str,
    confidence: float,
    reason: str = "",
) -> bool:
    """Return True if this edge should not be persisted.

    Low-confidence self-calls are usually resolver artifacts (method/fuzzy
    resolution mapping a call site back onto the same function id).  Direct
    recursion is typically ``direct_call`` / import-resolved at high
    confidence.
    """
    if from_function_id != to_function_id:
        return False
    if confidence >= CONF_IMPORT_RESOLVED:
        return False
    if reason == "fuzzy":
        return True
    # Typical bad case: method_call @ 0.7 resolving ``self.__init__``-style noise
    if reason == "method_call" and confidence < CONF_IMPORT_RESOLVED:
        return True
    return False
